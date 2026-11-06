#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Discovery helpers for the one mail module instance this module serves
# (DESIGN.md decision #2).
#
# The instance is bound to that mail module by its MODULE_UUID (decision
# #15), stored as MAIL_SERVER in the environment, the name ns8-piler and
# ns8-sogo use. The UUID survives a move or restore of the mail module,
# while its module id changes. Without a binding, the default is the
# nearest mail module that no other automx instance is bound to, since two
# instances on one mail module would overwrite each other's DNS records
# through dnshelper; reconcile() records that default once a domain is
# enabled, so a mail module installed later can't take over silently.
#
# Confirmed against a real read of NethServer/ns8-mail (DESIGN.md 3.2):
# get-configuration returns {"hostname", "user_domain"}, list-domains
# returns an array of {"domain", "addusers", "addgroups", "addaliases",
# "catchall", "bccaddr", "description"} with no per-domain ports or
# user_domain.
#
# get-configuration's "user_domain" is a full descriptor object (from
# ns8-core's cluster.userdomains.list_domains(), keyed by domain name but
# returning the *value* dict, which itself repeats the name in a "name"
# field), not a plain domain-name string -- get_instance_info() below
# extracts that "name" field, since that's the string Ldapproxy() and
# agent.bind_user_domains() actually take (DESIGN.md 3.3).

import os

import agent

# Every internal call hides its task from the admin UI's notifications:
# refresh-aliases makes these calls every 15 minutes, and each one showed
# up as a bare "Completed" notification (found on a real node, 2026-09-29).
HIDDEN = {"isNotificationHidden": True}

# IMAPS/SMTPS are fixed, never advertised as configurable by ns8-mail
# (DESIGN.md decisions log #11, VERIFY item 1).
IMAP_PORT = 993
SMTP_PORT = 465

BINDING_VAR = "MAIL_SERVER"
IMAGE_NAME = "automx"


class MailNotFound(Exception):
    """No mail module instance is installed."""


class MailNotConfigured(Exception):
    """A mail instance exists but has no hostname/user_domain yet."""


def bound_uuid():
    """The UUID of the mail module this instance is bound to, or None."""
    return os.environ.get(BINDING_VAR) or None


def _provider(rdb, module_uuid=None):
    """The imap service record of module_uuid, else of the bound mail
    module, else of the nearest one no other automx instance is bound to;
    None if there is no such provider."""
    module_uuid = module_uuid or bound_uuid()
    if module_uuid:
        providers = agent.list_service_providers(rdb, "imap", "tcp", {"module_uuid": module_uuid})
        return providers[0] if providers else None
    providers = agent.list_service_providers(rdb, "imap", "tcp")
    if not providers:
        return None
    taken = users_of(rdb)
    return next((p for p in providers if p.get("module_uuid") not in taken), None)


def _is_mail_module(rdb, module_uuid):
    """Whether module_uuid belongs to an installed mail module, configured
    or not: ns8-mail publishes its imap key only once configured."""
    for module_id, uuid in (rdb.hgetall("cluster/module_uuid") or {}).items():
        if uuid == module_uuid:
            image_url = (rdb.hgetall(f"module/{module_id}/environment") or {}).get("IMAGE_URL")
            return bool(image_url) and agent.get_image_name_from_url(image_url) == "mail"
    return False


def find_instance(rdb, module_uuid=None):
    """Return the mail module_id (e.g. "mail1"), or None if absent."""
    provider = _provider(rdb, module_uuid)
    return provider["module_id"] if provider else None


def current_uuid(rdb):
    """The UUID in use: the binding, even if that module is gone, else the
    UUID of the module used by default. None without either, for example
    when every mail module is bound to another automx instance."""
    bound = bound_uuid()
    if bound:
        return bound
    provider = _provider(rdb)
    return provider["module_uuid"] if provider else None


def bind(module_uuid):
    """Store the binding. Later steps and services read it from the
    environment file; os.environ covers the rest of this process and the
    commands it runs (reconcile() starts reload-automx)."""
    agent.set_env(BINDING_VAR, module_uuid)
    os.environ[BINDING_VAR] = module_uuid


def ensure_bound(rdb):
    """Record the mail module in use if nothing is stored yet."""
    if bound_uuid():
        return
    provider = _provider(rdb)
    if provider:
        bind(provider["module_uuid"])


def users_of(rdb):
    """{mail module UUID: module id} of the other automx instances bound to a
    mail module, read from their environment in Redis. Two instances on one
    mail module would overwrite each other's DNS records through dnshelper."""
    own_id = os.environ.get("MODULE_ID")
    users = {}
    for module_id in sorted(rdb.hkeys("cluster/module_node") or []):
        if module_id == own_id:
            continue
        env = rdb.hgetall(f"module/{module_id}/environment") or {}
        image_url = env.get("IMAGE_URL")
        if image_url and agent.get_image_name_from_url(image_url) == IMAGE_NAME and env.get(BINDING_VAR):
            users.setdefault(env[BINDING_VAR], module_id)
    return users


def list_servers(rdb):
    """The mail modules of the cluster, nearest first, for the Settings page."""
    users = users_of(rdb)
    return [
        {
            "module_uuid": provider["module_uuid"],
            "module_id": provider["module_id"],
            "ui_name": provider.get("ui_name") or "",
            # Published only by recent ns8-mail releases.
            "hostname": provider.get("mail_hostname") or "",
            "user_domain": provider.get("user_domain") or "",
            "node": provider.get("node") or "",
            "used_by": users.get(provider["module_uuid"]),
        }
        for provider in agent.list_service_providers(rdb, "imap", "tcp")
    ]


def get_configuration(mail_module_id):
    """{"hostname": str, "user_domain": dict}, from the mail module's own
    get-configuration action."""
    response = agent.tasks.run(f"module/{mail_module_id}", action="get-configuration", data={}, extra=HIDDEN)
    agent.assert_exp(response["exit_code"] == 0, "mail get-configuration failed")
    return response["output"]


def list_domains(mail_module_id):
    """List of domain dicts as ns8-mail's list-domains returns them."""
    response = agent.tasks.run(f"module/{mail_module_id}", action="list-domains", data={}, extra=HIDDEN)
    agent.assert_exp(response["exit_code"] == 0, "mail list-domains failed")
    return response["output"]


def get_instance_info(rdb, module_uuid=None):
    """Convenience: (module_id, hostname, user_domain_name, domain_names)
    for the mail instance in use (or module_uuid), raising MailNotFound or
    MailNotConfigured instead of forcing every caller to re-check for
    None/missing fields.
    user_domain_name is the plain domain-name string (see module docstring),
    ready to pass to Ldapproxy()/agent.bind_user_domains()."""
    module_id = find_instance(rdb, module_uuid)
    if module_id is None:
        wanted = module_uuid or bound_uuid()
        if wanted and _is_mail_module(rdb, wanted):
            raise MailNotConfigured()
        raise MailNotFound()

    config = get_configuration(module_id)
    hostname = config.get("hostname")
    user_domain = config.get("user_domain")
    if not hostname or not user_domain:
        raise MailNotConfigured()

    domain_names = {d["domain"] for d in list_domains(module_id)}
    return module_id, hostname, user_domain["name"], domain_names

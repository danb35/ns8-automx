#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Discovery helpers for the (single, v1 -- DESIGN.md decision #2) mail
# module instance. Confirmed against a real read of NethServer/ns8-mail
# (DESIGN.md 3.2): get-configuration returns {"hostname", "user_domain"},
# list-domains returns an array of {"domain", "addusers", "addgroups",
# "addaliases", "catchall", "bccaddr", "description"} with no per-domain
# ports or user_domain.
#
# get-configuration's "user_domain" is a full descriptor object (from
# ns8-core's cluster.userdomains.list_domains(), keyed by domain name but
# returning the *value* dict, which itself repeats the name in a "name"
# field), not a plain domain-name string -- get_instance_info() below
# extracts that "name" field, since that's the string Ldapproxy() and
# agent.bind_user_domains() actually take (DESIGN.md 3.3).

import agent

# IMAPS/SMTPS are fixed, never advertised as configurable by ns8-mail
# (DESIGN.md decisions log #11, VERIFY item 1).
IMAP_PORT = 993
SMTP_PORT = 465


class MailNotFound(Exception):
    """No mail module instance is installed."""


class MailNotConfigured(Exception):
    """A mail instance exists but has no hostname/user_domain yet."""


def find_instance(rdb):
    """Return the mail module_id (e.g. "mail1"), or None if absent."""
    providers = agent.list_service_providers(rdb, "imap", "tcp")
    if not providers:
        return None
    # One mail instance in v1 -- take the first (DESIGN.md decision #2).
    return providers[0]["module_id"]


def get_configuration(mail_module_id):
    """{"hostname": str, "user_domain": dict}, from the mail module's own
    get-configuration action."""
    response = agent.tasks.run(f"module/{mail_module_id}", action="get-configuration", data={})
    agent.assert_exp(response["exit_code"] == 0, "mail get-configuration failed")
    return response["output"]


def list_domains(mail_module_id):
    """List of domain dicts as ns8-mail's list-domains returns them."""
    response = agent.tasks.run(f"module/{mail_module_id}", action="list-domains", data={})
    agent.assert_exp(response["exit_code"] == 0, "mail list-domains failed")
    return response["output"]


def get_instance_info(rdb):
    """Convenience: (module_id, hostname, user_domain_name, domain_names)
    for the single mail instance, raising MailNotFound/MailNotConfigured
    instead of forcing every caller to re-check for None/missing fields.
    user_domain_name is the plain domain-name string (see module docstring),
    ready to pass to Ldapproxy()/agent.bind_user_domains()."""
    module_id = find_instance(rdb)
    if module_id is None:
        raise MailNotFound()

    config = get_configuration(module_id)
    hostname = config.get("hostname")
    user_domain = config.get("user_domain")
    if not hostname or not user_domain:
        raise MailNotConfigured()

    domain_names = {d["domain"] for d in list_domains(module_id)}
    return module_id, hostname, user_domain["name"], domain_names

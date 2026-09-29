#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Discovery of the groupware modules whose CalDAV/CardDAV and ActiveSync
# endpoints this module can publish (DESIGN.md 2, v2 scope). Read from the
# NS8 modules' own sources (2026-09-29):
#
#   - Nextcloud (NethServer/ns8-nextcloud): DAV at /remote.php/dav/, no
#     ActiveSync. Its host is kept only in its own config.json, not in its
#     environment, so it's read from its Traefik route (instance name =
#     module id) -- which this module can only query on its own node
#     (traefik@node:routeadm).
#   - SOGo (NethServer/ns8-sogo): TRAEFIK_HOST; DAV at /SOGo/dav/ when its
#     DAV flag is on; ActiveSync at /Microsoft-Server-ActiveSync when its
#     ACTIVESYNC flag is on (templates/SOGo.conf). MAIL_SERVER is the UUID
#     of the mail module it uses.
#   - WebTop (NethServer/ns8-webtop): WEBTOP_HOSTNAME; DAV at
#     /webtop-dav/server.php, z-push ActiveSync at
#     /Microsoft-Server-ActiveSync (apache/vhosts/*.conf); neither can be
#     switched off. MAIL_MODULE_UUID is the UUID of its mail module.
#
# Any module agent may read every module/<id>/environment hash (the Redis
# ACL ns8-core's add-module grants), so no extra authorization is needed.
#
# A DAV login is the directory login, so DAV needs the module bound to the
# same user domain as the mail instance. ActiveSync also carries the mail
# itself, so it additionally needs the same mail module.

import os

import agent

DAV_PATHS = {
    "nextcloud": "/remote.php/dav/",
    "sogo": "/SOGo/dav/",
    "webtop": "/webtop-dav/server.php",
}
ACTIVESYNC_PATH = "/Microsoft-Server-ActiveSync"
MAIL_UUID_VARS = {"sogo": "MAIL_SERVER", "webtop": "MAIL_MODULE_UUID"}


def _flag(value, default=True):
    # SOGo stores its booleans with agent.set_env(), i.e. as "True"/"False".
    if value is None:
        return default
    return value.strip().lower() == "true"


def _module_ids(rdb):
    return sorted(rdb.hkeys("cluster/module_node") or [])


def _nextcloud_host(module_id, env):
    if env.get("NODE_ID") != os.environ.get("NODE_ID"):
        return None
    route = agent.get_route(module_id)
    return (route or {}).get("host") or None


def _host(kind, module_id, env):
    if kind == "sogo":
        return env.get("TRAEFIK_HOST") or None
    if kind == "webtop":
        return env.get("WEBTOP_HOSTNAME") or None
    return _nextcloud_host(module_id, env)


def list_candidates(rdb, mail_module_id, user_domain):
    """Groupware modules usable for this mail instance, as a list of
    {"module_id", "kind", "host", "dav_url", "activesync_url"}, sorted by
    module_id. dav_url/activesync_url are None where that service is
    unavailable; a module offering neither is left out."""
    mail_uuid = rdb.hget(f"module/{mail_module_id}/environment", "MODULE_UUID")
    candidates = []
    for module_id in _module_ids(rdb):
        env = rdb.hgetall(f"module/{module_id}/environment") or {}
        image_url = env.get("IMAGE_URL")
        if not image_url:
            continue
        kind = agent.get_image_name_from_url(image_url)
        if kind not in DAV_PATHS:
            continue
        if user_domain not in agent.get_bound_domain_list(rdb, module_id):
            continue
        host = _host(kind, module_id, env)
        if not host:
            continue

        dav_url = None
        if kind != "sogo" or _flag(env.get("DAV")):
            dav_url = f"https://{host}{DAV_PATHS[kind]}"

        activesync_url = None
        uuid_var = MAIL_UUID_VARS.get(kind)
        same_mail = uuid_var is not None and mail_uuid is not None and env.get(uuid_var) == mail_uuid
        if same_mail and (kind != "sogo" or _flag(env.get("ACTIVESYNC"))):
            activesync_url = f"https://{host}{ACTIVESYNC_PATH}"

        if dav_url or activesync_url:
            candidates.append(
                {
                    "module_id": module_id,
                    "kind": kind,
                    "host": host,
                    "dav_url": dav_url,
                    "activesync_url": activesync_url,
                }
            )
    return candidates


def find(candidates, module_id, service):
    """The URL of service ("dav_url" or "activesync_url") of module_id among
    candidates, or None if that module isn't a usable provider of it."""
    for candidate in candidates:
        if candidate["module_id"] == module_id:
            return candidate[service]
    return None

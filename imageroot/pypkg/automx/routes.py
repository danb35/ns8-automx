#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Traefik route management (DESIGN.md 3.4/4.4), built on the confirmed
# set-route/delete-route contract (2026-09-22 read of NethServer/ns8-traefik):
# instance (required, idempotency key -- re-set-route with the same instance
# merges fields into the existing route), url, host, path (a single
# path-prefix filter; several instances CAN share one host with different
# path values), priority, lets_encrypt(_check|_cleanup), http2https.
#
# Route instance names embed MODULE_ID so ns8-traefik's own module-removed
# handler auto-cleans them on module removal (no explicit delete-route
# needed there); explicit delete-route is only for disabling one domain
# while the module stays installed (set_domains below).

import os

import agent

# automx's actual served paths (DESIGN.md 3.4, confirmed against
# src/automx/app.py): each needs its own route since `path` is a single
# prefix, not a list. The capitalized Autodiscover variant Outlook
# sometimes uses is a known v1 gap (3.4) -- not routed, no rewrite
# capability was confirmed for it.
AUTOCONFIG_PATHS = (
    "/mail/config-v1.1.xml",
    "/.well-known/autoconfig/mail/config-v1.1.xml",
    "/mobileconfig",
    "/mobileconfig.css",
    "/mobileconfig.js",
)
AUTODISCOVER_PATH = "/autodiscover/autodiscover.xml"


def instance_name(module_id, kind, domain, index):
    # e.g. "automx1-autoconfig-example.com-0" -- unique per host+path,
    # embeds MODULE_ID for ns8-traefik's own cleanup-on-removal matching.
    return f"{module_id}-{kind}-{domain}-{index}"


def _upstream_url():
    return f"http://127.0.0.1:{os.environ['TCP_PORT']}"


def _set(instance, host, path, http2https):
    data = {
        "instance": instance,
        "url": _upstream_url(),
        "host": host,
        "path": path,
        "lets_encrypt": True,
        "http2https": http2https,
    }
    # error_passthrough=False: a DNS-not-ready ACME failure must become a
    # handled status (DESIGN.md 3.4/5.6, "mark the domain waiting for DNS"),
    # not an aborted action.
    return agent.set_route(data, error_passthrough=False)


def set_domain_routes(module_id, domain, http2https):
    """Create/update the autoconfig.<domain> and autodiscover.<domain>
    routes for one enabled domain. Returns a list of (instance, response)
    for any call whose exit_code != 0 (DNS not ready, refused, ...) so the
    caller can report per-route failures instead of a single opaque one."""
    failures = []

    for index, path in enumerate(AUTOCONFIG_PATHS):
        instance = instance_name(module_id, "autoconfig", domain, index)
        response = _set(instance, f"autoconfig.{domain}", path, http2https)
        if response["exit_code"] != 0:
            failures.append((instance, response))

    instance = instance_name(module_id, "autodiscover", domain, 0)
    response = _set(instance, f"autodiscover.{domain}", AUTODISCOVER_PATH, http2https)
    if response["exit_code"] != 0:
        failures.append((instance, response))

    return failures


def delete_domain_routes(module_id, domain):
    """Remove one domain's routes (DESIGN.md 5.5, disabling a domain).
    Full-module removal doesn't need this: ns8-traefik's own module-removed
    handler cleans up every route whose instance name contains module_id."""
    target = agent.resolve_agent_id("traefik@node")
    instances = [instance_name(module_id, "autoconfig", domain, i) for i in range(len(AUTOCONFIG_PATHS))]
    instances.append(instance_name(module_id, "autodiscover", domain, 0))
    for instance in instances:
        agent.tasks.run(agent_id=target, action="delete-route", data={"instance": instance})


def node_autodiscover_instance(module_id):
    return f"{module_id}-node-autodiscover"


def set_node_autodiscover_route(module_id, node_fqdn, http2https):
    """The single route on the node's own FQDN, restricted to the
    Autodiscover path (DESIGN.md 4.4) -- SRV records point Outlook here.
    NS8 core sets up no host-based catch-all for the bare node FQDN (3.4),
    so this doesn't collide with anything core manages."""
    instance = node_autodiscover_instance(module_id)
    return _set(instance, node_fqdn, AUTODISCOVER_PATH, http2https)


def delete_node_autodiscover_route(module_id):
    target = agent.resolve_agent_id("traefik@node")
    agent.tasks.run(
        agent_id=target,
        action="delete-route",
        data={"instance": node_autodiscover_instance(module_id)},
    )

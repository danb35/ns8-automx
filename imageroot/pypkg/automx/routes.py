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
import sys

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


def domain_route_exists(module_id, domain):
    """True if this domain's routes have already been created. Used to
    gate first-time route creation on DNS readiness (DESIGN.md 5.6) without
    re-checking, or tearing down, a domain whose routes already exist --
    a transient DNS/dnshelper hiccup on a later reconcile must never delete
    a working route and force Traefik to burn a fresh Let's Encrypt attempt
    for no reason. Checking the autoconfig instance is enough: all of one
    domain's route instances are created together in set_domain_routes.

    PATCH, found live 2026-09-24: agent.get_route() returns {} (falsy, but
    not None) for a route that doesn't exist -- confirmed against the real
    SDK by the fact that stub_agent.py already modeled it that way
    (get_route_result defaults to {}, not None) while this function still
    used `is not None`, which treats {} as "exists". That silently disabled
    the DNS gate for every domain, unconditionally, every time: a brand
    new domain with zero routes was always treated as "already has routes"
    and skipped straight to creating them regardless of DNS status -- the
    exact bug this function exists to prevent. get-domains/10read's
    original pre-refactor check (`if agent.get_route(instance):`) was a
    plain truthiness test and never had this bug; this is that same test,
    restored."""
    return bool(agent.get_route(instance_name(module_id, "autoconfig", domain, 0)))


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


def _delete(instance):
    """Best-effort delete-route: logs a warning on failure instead of
    silently discarding the result (found in audit, 2026-09-24 -- every
    other tasks.run call in this codebase checks exit_code, this one
    didn't). Not fatal: a stale route left behind after a failed delete is
    a much smaller problem than aborting the whole disable/removal flow
    over it, matching set-domains/10apply's own best-effort handling of a
    failed DNS-record removal."""
    target = agent.resolve_agent_id("traefik@node")
    response = agent.tasks.run(agent_id=target, action="delete-route", data={"instance": instance})
    if response["exit_code"] != 0:
        print(
            agent.SD_WARNING + f"could not delete route {instance}: {response['error'] or response}",
            file=sys.stderr,
        )


def delete_domain_routes(module_id, domain):
    """Remove one domain's routes (DESIGN.md 5.5, disabling a domain).
    Full-module removal doesn't need this: ns8-traefik's own module-removed
    handler cleans up every route whose instance name contains module_id."""
    instances = [instance_name(module_id, "autoconfig", domain, i) for i in range(len(AUTOCONFIG_PATHS))]
    instances.append(instance_name(module_id, "autodiscover", domain, 0))
    for instance in instances:
        _delete(instance)


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
    _delete(node_autodiscover_instance(module_id))

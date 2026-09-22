#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The reconciliation configure-module and set-domains both need after a
# state change: (re-)apply Traefik routes for every enabled/usable domain
# plus the shared node-FQDN Autodiscover route, then render + validate +
# restart automx itself (imageroot/bin/reload-automx).
#
# Route creation is attempted for every enabled domain even if its DNS
# isn't resolvable yet (DESIGN.md 5.6): ns8-traefik has no retry/backoff of
# its own (3.4), so "wait, then retry automatically" isn't available to us
# either -- callers surface per-domain failures (e.g. "waiting for DNS")
# from the returned dict instead, and the admin can re-run set-domains (or
# a future check-dns-triggered re-apply) once DNS is in place.

import os
import subprocess
import sys

from automx import mail, node, routes, state


def reconcile(rdb):
    """Re-applies routes for all enabled+usable domains and reloads automx.
    Returns {"route_failures": {domain: [(instance, response), ...]},
    "node_route_failure": (instance, response)|None}."""
    domains_state = state.load_domains()
    settings = state.load_settings()
    module_id = os.environ["MODULE_ID"]

    try:
        _mail_module_id, _hostname, _user_domain, mail_domain_names = mail.get_instance_info(rdb)
    except (mail.MailNotFound, mail.MailNotConfigured):
        mail_domain_names = set()

    enabled_domains = sorted(
        domain
        for domain, flags in domains_state.items()
        if flags.get("enabled") and domain in mail_domain_names
    )

    route_failures = {}
    for domain in enabled_domains:
        failures = routes.set_domain_routes(module_id, domain, settings["http2https"])
        if failures:
            route_failures[domain] = failures

    node_route_failure = None
    if enabled_domains:
        node_fqdn = settings.get("service_host") or node.get_node_fqdn()
        response = routes.set_node_autodiscover_route(module_id, node_fqdn, settings["http2https"])
        if response["exit_code"] != 0:
            node_route_failure = (routes.node_autodiscover_instance(module_id), response)
    else:
        routes.delete_node_autodiscover_route(module_id)

    reload_result = subprocess.run(
        [os.path.join(os.environ["AGENT_INSTALL_DIR"], "bin", "reload-automx")],
        capture_output=True,
        text=True,
    )
    if reload_result.returncode != 0:
        print(reload_result.stderr, file=sys.stderr, end="")

    return {
        "route_failures": route_failures,
        "node_route_failure": node_route_failure,
        "reload_failed": reload_result.returncode != 0,
    }

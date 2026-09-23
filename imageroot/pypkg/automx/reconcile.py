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
#
# Six call sites reach reconcile(): set-domains, configure-module,
# restore-module, and three event handlers (mail-settings-changed,
# user-domain-changed, module-domain-changed) -- any pair of which can fire
# close together in real use (e.g. an admin's own action landing while an
# event handler is mid-run). A single render (render-automx-conf) takes
# ~20s on a real node -- NS8's task-based RPCs for mail/node data each cost
# several seconds -- and a full reconcile does two (reload-automx's own
# staged render, then automx.service's ExecStartPre render on restart), so
# ~45s is a realistic window for two reconcile() calls to overlap. Found on
# a real node, 2026-09-22: an overlapping `systemctl stop` (from one call's
# reload-automx) landed on a still-starting automx.service (another call's
# `systemctl restart` mid-ExecStartPre) and killed it with SIGTERM,
# recorded by systemd as "Result: signal" -- a real failure state, not the
# harmless "stopped because zero domains" case, and one SuccessExitStatus
# can't paper over since it's a killed signal, not a controlled exit code.
#
# A blocking flock() serializes reconcile() itself -- but that alone isn't
# enough for set-domains: it reads, mutates and writes state/domains.json
# *before* calling reconcile() (imageroot/actions/set-domains/10apply), so
# two concurrent set-domains calls can still interleave their domains.json
# writes around each other's reconcile(). Found on the same real node right
# after the reconcile()-only lock was verified: two overlapping set-domains
# calls no longer raced on SIGTERM, but automx.service still ended up
# "failed (Result: exit-code)" -- one call's `systemctl restart` completed,
# then the *other* call's already-in-flight domains.json write landed
# before that restart's own automx.service ExecStartPre re-render actually
# ran (it always re-renders from disk on every start, DESIGN.md 4.2), so
# that fresh render saw a state its own caller never intended (zero
# domains) and correctly exited EXIT_NOTHING_TO_RENDER -- which systemd
# still treats as a failed *start*, not a graceful no-op.
#
# lock() is exported so set-domains/10apply can hold the same lock across
# its own load-mutate-save of domains.json *and* the reconcile that
# follows, closing this second race at its actual source instead of only
# inside reconcile()'s own body. Every other caller only ever calls
# reconcile() with no state write of its own, so reconcile() keeps
# acquiring the lock itself for them.

import fcntl
import os
import subprocess
import sys
from contextlib import contextmanager

from automx import domains, mail, node, routes, state


@contextmanager
def lock():
    """Context manager for the reconcile lock (see module docstring). Yields
    nothing; used by set-domains/10apply to hold the lock across its own
    domains.json read-modify-write plus the reconcile_locked() call that
    follows, and internally by reconcile() for every other caller."""
    lock_path = os.path.join(state.STATE_DIR, "reconcile.lock")
    lock_file = open(lock_path, "w")
    fcntl.flock(lock_file, fcntl.LOCK_EX)
    try:
        yield
    finally:
        lock_file.close()  # also releases the flock


def reconcile(rdb):
    """Re-applies routes for all enabled+usable domains and reloads automx.
    Returns {"route_failures": {domain: [(instance, response), ...]},
    "node_route_failure": (instance, response)|None}. Acquires the shared
    lock itself -- callers that also need to mutate state/domains.json
    under the same lock (currently only set-domains/10apply) should use
    lock() + reconcile_locked() directly instead."""
    with lock():
        return reconcile_locked(rdb)


def reconcile_locked(rdb):
    domains_state = state.load_domains()
    settings = state.load_settings()
    module_id = os.environ["MODULE_ID"]

    try:
        _mail_module_id, _hostname, _user_domain, mail_domain_names = mail.get_instance_info(rdb)
    except (mail.MailNotFound, mail.MailNotConfigured):
        mail_domain_names = set()

    enabled_domains = domains.enabled_usable(mail_domain_names, domains_state)

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

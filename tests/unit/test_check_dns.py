#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit test for imageroot/actions/check-dns/10check's reconcile trigger,
# added alongside the DNS-before-routes gate (DESIGN.md 5.6). Route
# creation for a domain is deliberately skipped while its DNS isn't ready
# yet (reconcile.py); check-dns is the action guaranteed to run whenever
# there's reason to think DNS might be ready now (the DNS status dialog
# opening, "check again", or automatically after a dnshelper "create" --
# DnsStatusModal.confirm() calls check-dns right after apply-dns), so it's
# where reconcile() gets re-triggered to actually create those routes. This
# must only happen when something could plausibly have changed -- most
# check-dns calls change nothing and mustn't pay for a full (20-45s on a
# real node) reconcile.

import importlib.machinery
import importlib.util
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(REPO_ROOT, "imageroot", "pypkg"))
sys.path.insert(0, HERE)
import stub_agent  # noqa: E402

_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent}):
    from automx import dns, dnshelperclient, dnsstatus, node, reconcile, routes, state  # noqa: E402

# Registering these under their dotted names makes the script's own
# "from automx import ..." below reuse these exact (patchable) module
# objects instead of re-importing and getting separate ones -- same
# reasoning as test_module_domain_changed_event.py's identical fixup.
for _mod, _name in (
    (dns, "automx.dns"),
    (dnshelperclient, "automx.dnshelperclient"),
    (dnsstatus, "automx.dnsstatus"),
    (node, "automx.node"),
    (reconcile, "automx.reconcile"),
    (routes, "automx.routes"),
    (state, "automx.state"),
):
    sys.modules[_name] = _mod

ACTION_PATH = os.path.join(REPO_ROOT, "imageroot", "actions", "check-dns", "10check")


def run_check_dns(stdin_data, domains_state, dns_by_domain, route_exists_for, module_id="automx1"):
    """Runs the action script with the given stdin payload and pre-baked
    state. dns_by_domain maps domain -> the dns_status dict domain_dns_
    status() should return; route_exists_for is a set of domains
    domain_route_exists() should report as already routed. Returns the
    reconcile.reconcile mock so call assertions can be made against it."""
    with mock.patch.object(state, "load_domains", return_value=domains_state), \
            mock.patch.object(state, "load_settings", return_value={}), \
            mock.patch.object(node, "get_node_fqdn", return_value="ns8.example.net"), \
            mock.patch.object(dnshelperclient, "find_instance", return_value=None), \
            mock.patch.object(
                dnsstatus, "domain_dns_status",
                side_effect=lambda domain, target_fqdn, dnshelper_target: dns_by_domain[domain],
            ), \
            mock.patch.object(
                routes, "domain_route_exists",
                side_effect=lambda mod_id, domain: domain in route_exists_for,
            ), \
            mock.patch.object(reconcile, "reconcile", return_value={}) as reconcile_mock, \
            mock.patch.dict(os.environ, {"MODULE_ID": module_id, "AGENT_INSTALL_DIR": os.path.join(REPO_ROOT, "imageroot")}), \
            mock.patch("json.load", return_value=stdin_data):
        loader = importlib.machinery.SourceFileLoader("check_dns_10check", ACTION_PATH)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"agent": _agent}):
            loader.exec_module(module)
    return reconcile_mock


READY = {"records": [{"type": "CNAME", "status": "ok"}]}
NOT_READY = {"records": [{"type": "CNAME", "status": "missing"}]}


class CheckDnsReconcileTriggerTests(unittest.TestCase):
    def test_reconciles_when_a_domain_is_newly_ready_and_routeless(self):
        reconcile_mock = run_check_dns(
            {},
            domains_state={"a.example": {"enabled": True}},
            dns_by_domain={"a.example": READY},
            route_exists_for=set(),
        )
        reconcile_mock.assert_called_once()

    def test_skips_when_dns_is_not_ready(self):
        reconcile_mock = run_check_dns(
            {},
            domains_state={"a.example": {"enabled": True}},
            dns_by_domain={"a.example": NOT_READY},
            route_exists_for=set(),
        )
        reconcile_mock.assert_not_called()

    def test_skips_when_the_domain_already_has_routes(self):
        # Nothing to do: reconcile() would be a no-op wait for no reason.
        reconcile_mock = run_check_dns(
            {},
            domains_state={"a.example": {"enabled": True}},
            dns_by_domain={"a.example": READY},
            route_exists_for={"a.example"},
        )
        reconcile_mock.assert_not_called()

    def test_skips_a_disabled_domain_even_if_its_dns_is_ready(self):
        reconcile_mock = run_check_dns(
            {},
            domains_state={"a.example": {"enabled": False}},
            dns_by_domain={"a.example": READY},
            route_exists_for=set(),
        )
        reconcile_mock.assert_not_called()

    def test_reconciles_once_even_with_several_domains_checked(self):
        reconcile_mock = run_check_dns(
            {},
            domains_state={"a.example": {"enabled": True}, "b.example": {"enabled": True}},
            dns_by_domain={"a.example": NOT_READY, "b.example": READY},
            route_exists_for=set(),
        )
        reconcile_mock.assert_called_once()

    def test_single_domain_request_only_checks_that_domain(self):
        reconcile_mock = run_check_dns(
            {"domain": "a.example"},
            domains_state={"a.example": {"enabled": True}, "b.example": {"enabled": True}},
            dns_by_domain={"a.example": NOT_READY, "b.example": READY},
            route_exists_for=set(),
        )
        # b.example is ready but was never checked (not in this request),
        # so nothing here should trigger a reconcile.
        reconcile_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit test for automx.reconcile's serialization lock. Added after two
# real-node findings (2026-09-22): set-domains, configure-module,
# restore-module and three event handlers all call reconcile(), and a
# single reconcile takes tens of seconds on a real node (two renders, each
# involving several-second NS8 task RPCs) -- long enough for two of these
# six call sites to genuinely overlap in normal use. First, an overlapping
# `systemctl stop` landing on a still-starting automx.service killed it
# with SIGTERM. Fixing that with a lock around reconcile() alone surfaced a
# second race: set-domains/10apply mutates state/domains.json *before*
# calling reconcile(), so two concurrent set-domains calls could still
# interleave their writes around each other's render/restart cycle. The
# fix widens the same lock to cover that read-modify-write too (see
# reconcile.py's lock()/reconcile_locked() split). These tests prove the
# lock actually serializes callers, not that the reconcile logic itself is
# correct (that needs the full agent/routes/mail stack this file doesn't
# stub).

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "imageroot", "pypkg"))
sys.path.insert(0, HERE)
import stub_agent  # noqa: E402

_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent, "agent.ldapproxy": _agent.ldapproxy}):
    from automx import reconcile  # noqa: E402


class ReconcileLockTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.state_patch = mock.patch.object(reconcile.state, "STATE_DIR", self.tmpdir.name)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def test_concurrent_reconcile_calls_are_serialized_not_interleaved(self):
        # reconcile_locked sleeps briefly while "holding" a shared counter,
        # simulating the real several-seconds-long body: if the lock didn't
        # serialize callers, both threads would see the counter at 0 when
        # they check it, since they'd run their critical sections
        # concurrently. With the lock, the second thread only starts its
        # body after the first has fully finished and incremented it.
        calls_in_progress = []
        max_concurrent = []

        def fake_locked_body(rdb):
            calls_in_progress.append(1)
            max_concurrent.append(len(calls_in_progress))
            time.sleep(0.05)
            calls_in_progress.pop()
            return {"route_failures": {}, "node_route_failure": None, "reload_failed": False}

        with mock.patch.object(reconcile, "reconcile_locked", side_effect=fake_locked_body):
            threads = [threading.Thread(target=reconcile.reconcile, args=(None,)) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        self.assertEqual(max(max_concurrent), 1, "reconcile() allowed overlapping critical sections")

    def test_lock_file_created_under_state_dir(self):
        with mock.patch.object(reconcile, "reconcile_locked", return_value={}):
            reconcile.reconcile(None)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir.name, "reconcile.lock")))

    def test_caller_holding_lock_directly_still_serializes_against_reconcile(self):
        # This is the set-domains/10apply pattern: a caller acquires
        # reconcile.lock() itself (to also guard its own state.json
        # write, not modeled here) and calls reconcile_locked() while
        # holding it. A plain reconcile() call from another thread must
        # still block until that caller releases the lock -- proving
        # lock() and reconcile()'s own internal use of it are the same
        # lock, not two independent ones.
        calls_in_progress = []
        max_concurrent = []

        def fake_locked_body(rdb):
            calls_in_progress.append(1)
            max_concurrent.append(len(calls_in_progress))
            time.sleep(0.05)
            calls_in_progress.pop()
            return {"route_failures": {}, "node_route_failure": None, "reload_failed": False}

        def caller_holding_lock_directly():
            with reconcile.lock():
                fake_locked_body(None)

        with mock.patch.object(reconcile, "reconcile_locked", side_effect=fake_locked_body):
            t1 = threading.Thread(target=caller_holding_lock_directly)
            t2 = threading.Thread(target=reconcile.reconcile, args=(None,))
            t1.start()
            time.sleep(0.01)  # give t1 a head start on acquiring the lock
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

        self.assertEqual(max(max_concurrent), 1, "lock() and reconcile()'s internal lock didn't serialize")


class ReconcileDnsGateTests(unittest.TestCase):
    # DESIGN.md 5.6: reconcile_locked() must not create a domain's routes
    # before its DNS resolves, must not re-check (or tear down) a domain
    # that already has routes, and must report a skipped domain in
    # "waiting_for_dns". Unlike ReconcileLockTests above, these mock only
    # the automx submodules reconcile.py itself calls (mail, domains,
    # dnsstatus, routes, node, dnshelperclient, state) and run the real
    # reconcile_locked() body -- the one piece of actual reconcile logic
    # this file tests, per its own module docstring's caveat.

    def setUp(self):
        patches = {
            "state.load_domains": {"a.example": {"enabled": True}, "b.example": {"enabled": True}},
            "state.load_settings": {"http2https": True},
            "mail.get_instance_info": ("mail1", "mail.example", "example", {"a.example", "b.example"}),
            "node.get_node_fqdn": "ns8.example.net",
            "dnshelperclient.find_instance": "module/dnshelper1",
        }
        self.mocks = {}
        self._patch("state", "load_domains", return_value=patches["state.load_domains"])
        self._patch("state", "load_settings", return_value=patches["state.load_settings"])
        self._patch("mail", "get_instance_info", return_value=patches["mail.get_instance_info"])
        self._patch("node", "get_node_fqdn", return_value=patches["node.get_node_fqdn"])
        self._patch("dnshelperclient", "find_instance", return_value=patches["dnshelperclient.find_instance"])
        self._patch("routes", "set_node_autodiscover_route", return_value={"exit_code": 0})
        self._patch("routes", "node_autodiscover_instance", return_value="automx1-node-autodiscover")
        self._patch("routes", "delete_node_autodiscover_route", return_value=None)
        self._patch("routes", "set_domain_routes", return_value=[])
        self._patch_env = mock.patch.dict(
            os.environ, {"MODULE_ID": "automx1", "AGENT_INSTALL_DIR": "/nonexistent"}
        )
        self._patch_env.start()
        self.addCleanup(self._patch_env.stop)
        self._subprocess_patch = mock.patch.object(
            reconcile.subprocess, "run", return_value=mock.Mock(returncode=0, stderr="")
        )
        self._subprocess_patch.start()
        self.addCleanup(self._subprocess_patch.stop)

    def _patch(self, module_name, attr, **kwargs):
        module = getattr(reconcile, module_name)
        p = mock.patch.object(module, attr, **kwargs)
        m = p.start()
        self.addCleanup(p.stop)
        self.mocks[f"{module_name}.{attr}"] = m
        return m

    def test_domain_without_a_route_and_dns_not_ready_is_skipped_and_reported(self):
        self._patch("routes", "domain_route_exists", return_value=False)
        self._patch(
            "dnsstatus",
            "domain_dns_status",
            return_value={"records": [{"type": "CNAME", "status": "missing"}]},
        )

        result = reconcile.reconcile_locked(None)

        self.assertEqual(sorted(result["waiting_for_dns"]), ["a.example", "b.example"])
        self.assertEqual(result["route_failures"], {})
        self.mocks["routes.set_domain_routes"].assert_not_called()

    def test_domain_without_a_route_and_dns_ready_gets_routes_created(self):
        self._patch("routes", "domain_route_exists", return_value=False)
        self._patch(
            "dnsstatus",
            "domain_dns_status",
            return_value={"records": [{"type": "CNAME", "status": "ok"}]},
        )

        result = reconcile.reconcile_locked(None)

        self.assertEqual(result["waiting_for_dns"], [])
        self.assertEqual(self.mocks["routes.set_domain_routes"].call_count, 2)

    def test_domain_with_an_existing_route_is_never_dns_checked_or_skipped(self):
        # A domain that already has routes must keep them regardless of
        # what a live DNS check says right now (reconcile.py's own
        # comment): a transient dnshelper/resolver hiccup must never tear
        # down a working route. Proven here by making domain_dns_status
        # itself raise -- if reconcile_locked() called it for this domain
        # at all, the test would error out instead of passing.
        self._patch("routes", "domain_route_exists", return_value=True)
        self._patch("dnsstatus", "domain_dns_status", side_effect=AssertionError("must not be called"))

        result = reconcile.reconcile_locked(None)

        self.assertEqual(result["waiting_for_dns"], [])
        self.assertEqual(self.mocks["routes.set_domain_routes"].call_count, 2)

    def test_mixed_one_domain_ready_one_not(self):
        self._patch("routes", "domain_route_exists", return_value=False)

        def dns_status(domain, target_fqdn, dnshelper_target):
            ok = domain == "a.example"
            return {"records": [{"type": "CNAME", "status": "ok" if ok else "missing"}]}

        self._patch("dnsstatus", "domain_dns_status", side_effect=dns_status)

        result = reconcile.reconcile_locked(None)

        self.assertEqual(result["waiting_for_dns"], ["b.example"])
        self.mocks["routes.set_domain_routes"].assert_called_once()
        self.assertEqual(self.mocks["routes.set_domain_routes"].call_args.args[1], "a.example")


if __name__ == "__main__":
    unittest.main()

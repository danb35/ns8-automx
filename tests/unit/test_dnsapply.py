#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit tests for automx.dnsapply.plan_changes: the create/overwrite
# record-change logic behind apply-dns (DESIGN.md 5.3.4).

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "imageroot", "pypkg"))
sys.path.insert(0, HERE)
import stub_agent  # noqa: E402

# dnsapply imports dnshelperclient, which imports "agent" at module level
# even though plan_changes() itself never calls it -- inject the stub so
# the import succeeds outside a real NS8 node.
_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent, "agent.ldapproxy": _agent.ldapproxy}):
    from automx import dns, dnsapply  # noqa: E402


ZONE = "example.com"
TARGET = "node.example.net"
# expected_records() appends a trailing dot to the target (2026-09-22 fix,
# see dns.py) -- dnshelper's own get-records returns written CNAME/SRV
# targets the same way, so "existing" fixtures below use this form too.
TARGET_ABSOLUTE = TARGET + "."


def expected():
    return dns.expected_records("mail.example.com", TARGET)


class CreateTests(unittest.TestCase):
    def test_all_missing_appends_everything(self):
        changes = dnsapply.plan_changes(ZONE, expected(), [], "create")
        self.assertEqual(changes["delete"], [])
        self.assertEqual(changes["set"], [])
        self.assertEqual(
            [(r["name"], r["type"]) for r in changes["append"]],
            [("autoconfig.mail", "CNAME"), ("autodiscover.mail", "CNAME"), ("_autodiscover._tcp.mail", "SRV")],
        )

    def test_ok_records_are_untouched(self):
        existing = [
            {"name": "autoconfig.mail", "type": "CNAME", "ttl": 3600, "data": TARGET_ABSOLUTE},
            {"name": "autodiscover.mail", "type": "CNAME", "ttl": 3600, "data": TARGET_ABSOLUTE},
            {"name": "_autodiscover._tcp.mail", "type": "SRV", "ttl": 3600, "data": f"0 0 443 {TARGET_ABSOLUTE}"},
        ]
        changes = dnsapply.plan_changes(ZONE, expected(), existing, "create")
        self.assertEqual(changes, {"delete": [], "append": [], "set": []})

    def test_create_never_touches_conflicts(self):
        # DESIGN.md 5.3.4: "Create: append-records for missing records" --
        # conflicts are an overwrite-only concern.
        existing = [{"name": "autoconfig.mail", "type": "A", "ttl": 3600, "data": "203.0.113.1"}]
        changes = dnsapply.plan_changes(ZONE, expected(), existing, "create")
        self.assertEqual(changes["delete"], [])
        self.assertEqual(changes["set"], [])
        appended_names = {r["name"] for r in changes["append"]}
        self.assertNotIn("autoconfig.mail", appended_names)
        self.assertIn("autodiscover.mail", appended_names)


class OverwriteTests(unittest.TestCase):
    def test_same_type_wrong_value_uses_set(self):
        existing = [{"name": "autoconfig.mail", "type": "CNAME", "ttl": 3600, "data": "old.example.net"}]
        changes = dnsapply.plan_changes(ZONE, [expected()[0]], existing, "overwrite")
        self.assertEqual(changes["delete"], [])
        self.assertEqual(changes["append"], [])
        self.assertEqual(len(changes["set"]), 1)
        self.assertEqual(changes["set"][0], {"name": "autoconfig.mail", "type": "CNAME", "data": TARGET_ABSOLUTE})

    def test_type_conflict_deletes_then_appends_the_cname(self):
        # DESIGN.md 5.3.4: a type conflict needs delete-records naming name
        # and type, THEN append the CNAME -- not set-records, since
        # dnshelper refuses a CNAME beside another record.
        existing = [
            {"name": "autoconfig.mail", "type": "A", "ttl": 3600, "data": "203.0.113.1"},
            {"name": "autoconfig.mail", "type": "TXT", "ttl": 3600, "data": "unrelated"},
        ]
        changes = dnsapply.plan_changes(ZONE, [expected()[0]], existing, "overwrite")
        self.assertEqual(changes["set"], [])
        self.assertEqual(
            sorted((r["name"], r["type"]) for r in changes["delete"]),
            [("autoconfig.mail", "A"), ("autoconfig.mail", "TXT")],
        )
        self.assertEqual(changes["append"], [{"name": "autoconfig.mail", "type": "CNAME", "data": TARGET_ABSOLUTE}])

    def test_srv_conflict_replaces_the_whole_rrset_via_set(self):
        srv = expected()[2]
        existing = [
            {"name": "_autodiscover._tcp.mail", "type": "SRV", "ttl": 3600, "data": "0 0 443 old.example.net"}
        ]
        changes = dnsapply.plan_changes(ZONE, [srv], existing, "overwrite")
        self.assertEqual(changes["delete"], [])
        self.assertEqual(changes["append"], [])
        self.assertEqual(changes["set"], [{"name": "_autodiscover._tcp.mail", "type": "SRV", "data": srv["value"]}])

    def test_overwrite_still_appends_missing_records(self):
        changes = dnsapply.plan_changes(ZONE, expected(), [], "overwrite")
        self.assertEqual(len(changes["append"]), 3)


class ApplyChangesTests(unittest.TestCase):
    """Real-node finding, 2026-09-22: a dnshelper dry-run call previews
    against the zone exactly as it is right now -- so a dry-run
    append-records for a CNAME that's only valid once a paired delete has
    actually happened always comes back rejected, not just a scarier-looking
    preview. apply_changes() must not ask dnshelper to dry-run that append at
    all; it should synthesize the preview from what plan_changes() already
    computed."""

    def test_type_conflict_dry_run_does_not_call_dnshelper_for_the_append(self):
        changes = {
            "delete": [{"name": "autoconfig", "type": "A"}],
            "append": [{"name": "autoconfig", "type": "CNAME", "data": "node.example.net."}],
            "set": [],
        }
        with mock.patch.object(
            dnsapply.dnshelperclient, "delete_records", return_value={"dry_run": True, "changes": {}}
        ) as delete_mock, mock.patch.object(dnsapply.dnshelperclient, "append_records") as append_mock:
            responses = dnsapply.apply_changes("dnshelper1", ZONE, changes, dry_run=True)

        delete_mock.assert_called_once()
        append_mock.assert_not_called()
        self.assertEqual(responses["append"]["changes"]["add"], changes["append"])

    def test_type_conflict_real_execution_calls_dnshelper_for_both_in_order(self):
        changes = {
            "delete": [{"name": "autoconfig", "type": "A"}],
            "append": [{"name": "autoconfig", "type": "CNAME", "data": "node.example.net."}],
            "set": [],
        }
        calls = []
        with mock.patch.object(
            dnsapply.dnshelperclient,
            "delete_records",
            side_effect=lambda *a, **kw: calls.append("delete") or {"changes": {}},
        ), mock.patch.object(
            dnsapply.dnshelperclient,
            "append_records",
            side_effect=lambda *a, **kw: calls.append("append") or {"changes": {}},
        ):
            dnsapply.apply_changes("dnshelper1", ZONE, changes, dry_run=False)

        self.assertEqual(calls, ["delete", "append"])

    def test_append_only_no_delete_is_still_dry_run_through_dnshelper(self):
        # No paired delete -- dnshelper *can* meaningfully dry-run this one
        # (a plain append for a missing record), so it should still be
        # asked to.
        changes = {"delete": [], "append": [{"name": "autodiscover", "type": "CNAME", "data": "x."}], "set": []}
        with mock.patch.object(
            dnsapply.dnshelperclient, "append_records", return_value={"changes": {}}
        ) as append_mock:
            dnsapply.apply_changes("dnshelper1", ZONE, changes, dry_run=True)

        append_mock.assert_called_once_with("dnshelper1", ZONE, changes["append"], dry_run=True)


if __name__ == "__main__":
    unittest.main()

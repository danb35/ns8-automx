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
            {"name": "autoconfig.mail", "type": "CNAME", "ttl": 3600, "data": TARGET},
            {"name": "autodiscover.mail", "type": "CNAME", "ttl": 3600, "data": TARGET},
            {"name": "_autodiscover._tcp.mail", "type": "SRV", "ttl": 3600, "data": f"0 0 443 {TARGET}"},
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
        self.assertEqual(changes["set"][0], {"name": "autoconfig.mail", "type": "CNAME", "data": TARGET})

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
        self.assertEqual(changes["append"], [{"name": "autoconfig.mail", "type": "CNAME", "data": TARGET}])

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


if __name__ == "__main__":
    unittest.main()

#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit tests for automx.dns: the expected-record set (DESIGN.md 5.1) and
# the status-comparison model (5.2/5.3.3).

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "imageroot", "pypkg"))
import automx.dns as dns  # noqa: E402


class ExpectedRecordsTests(unittest.TestCase):
    def test_three_records_for_a_domain(self):
        records = dns.expected_records("example.com", "node.example.net")
        self.assertEqual(
            [(r["host"], r["type"]) for r in records],
            [
                ("autoconfig.example.com", "CNAME"),
                ("autodiscover.example.com", "CNAME"),
                ("_autodiscover._tcp.example.com", "SRV"),
            ],
        )
        srv = records[2]
        # Trailing dot: a target without one is zone-relative in standard
        # DNS, and dnshelper doesn't add one for us (found on a real node,
        # 2026-09-22 -- see expected_records()'s docstring).
        self.assertEqual(srv["value"], "0 0 443 node.example.net.")
        self.assertEqual(records[0]["value"], "node.example.net.")

    def test_target_fqdn_with_a_trailing_dot_already_is_not_doubled(self):
        records = dns.expected_records("example.com", "node.example.net.")
        self.assertEqual(records[0]["value"], "node.example.net.")


class RelativeNameTests(unittest.TestCase):
    def test_apex(self):
        self.assertEqual(dns.dnshelper_relative_name("example.com", "example.com"), "@")

    def test_direct_child(self):
        self.assertEqual(
            dns.dnshelper_relative_name("autoconfig.example.com", "example.com"),
            "autoconfig",
        )

    def test_mail_domain_is_a_subdomain_of_the_managed_zone(self):
        # DESIGN.md 5.3.1: "A mail domain can be a subdomain of the managed zone."
        self.assertEqual(
            dns.dnshelper_relative_name("autoconfig.mail.example.com", "example.com"),
            "autoconfig.mail",
        )

    def test_host_outside_zone_is_an_error(self):
        with self.assertRaises(ValueError):
            dns.dnshelper_relative_name("autoconfig.other.com", "example.com")


class CompareRecordTests(unittest.TestCase):
    def setUp(self):
        self.cname = {"host": "autoconfig.example.com", "type": "CNAME", "value": "node.example.net"}
        self.srv = {
            "host": "_autodiscover._tcp.example.com",
            "type": "SRV",
            "value": "0 0 443 node.example.net",
        }

    def test_cname_missing(self):
        status, conflicts = dns.compare_record(self.cname, [])
        self.assertEqual(status, dns.STATUS_MISSING)
        self.assertEqual(conflicts, [])

    def test_cname_ok(self):
        existing = [{"name": "autoconfig", "type": "CNAME", "ttl": 3600, "data": "node.example.net"}]
        status, conflicts = dns.compare_record(self.cname, existing)
        self.assertEqual(status, dns.STATUS_OK)
        self.assertEqual(conflicts, [])

    def test_cname_wrong_value_conflicts(self):
        existing = [{"name": "autoconfig", "type": "CNAME", "ttl": 3600, "data": "other.example.net"}]
        status, conflicts = dns.compare_record(self.cname, existing)
        self.assertEqual(status, dns.STATUS_CONFLICT)
        self.assertEqual(conflicts, existing)

    def test_cname_conflicts_with_any_other_record_at_the_name(self):
        # DESIGN.md 5.2/5.3.3: "A CNAME conflicts with any other record at
        # the same name" -- even one that isn't a CNAME at all.
        existing = [{"name": "autoconfig", "type": "A", "ttl": 3600, "data": "203.0.113.1"}]
        status, conflicts = dns.compare_record(self.cname, existing)
        self.assertEqual(status, dns.STATUS_CONFLICT)
        self.assertEqual(conflicts, existing)

    def test_cname_conflicts_when_multiple_records_share_the_name(self):
        existing = [
            {"name": "autoconfig", "type": "CNAME", "ttl": 3600, "data": "node.example.net"},
            {"name": "autoconfig", "type": "TXT", "ttl": 3600, "data": "unrelated"},
        ]
        status, conflicts = dns.compare_record(self.cname, existing)
        self.assertEqual(status, dns.STATUS_CONFLICT)

    def test_srv_missing(self):
        status, conflicts = dns.compare_record(self.srv, [])
        self.assertEqual(status, dns.STATUS_MISSING)

    def test_srv_ok(self):
        existing = [
            {"name": "_autodiscover._tcp", "type": "SRV", "ttl": 3600, "data": "0 0 443 node.example.net"}
        ]
        status, conflicts = dns.compare_record(self.srv, existing)
        self.assertEqual(status, dns.STATUS_OK)

    def test_srv_only_conflicts_with_a_different_srv_rrset(self):
        # DESIGN.md 5.2/5.3.3: "an SRV conflicts only with a different SRV
        # RRset at that name" -- an unrelated record type coexisting is fine.
        existing = [
            {"name": "_autodiscover._tcp", "type": "TXT", "ttl": 3600, "data": "unrelated"},
        ]
        status, conflicts = dns.compare_record(self.srv, existing)
        self.assertEqual(status, dns.STATUS_MISSING)

    def test_srv_wrong_target_conflicts(self):
        existing = [
            {"name": "_autodiscover._tcp", "type": "SRV", "ttl": 3600, "data": "0 0 443 other.example.net"}
        ]
        status, conflicts = dns.compare_record(self.srv, existing)
        self.assertEqual(status, dns.STATUS_CONFLICT)
        self.assertEqual(conflicts, existing)

    def test_srv_ok_when_one_of_several_matches(self):
        existing = [
            {"name": "_autodiscover._tcp", "type": "SRV", "ttl": 3600, "data": "0 0 443 other.example.net"},
            {"name": "_autodiscover._tcp", "type": "SRV", "ttl": 3600, "data": "0 0 443 node.example.net"},
        ]
        status, conflicts = dns.compare_record(self.srv, existing)
        self.assertEqual(status, dns.STATUS_OK)


if __name__ == "__main__":
    unittest.main()

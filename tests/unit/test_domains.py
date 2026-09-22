#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit tests for automx.domains: merging the mail module's current domain
# list with our own stored enable flags, and orphan handling (DESIGN.md 4.2).

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "imageroot", "pypkg"))
import automx.domains as domains  # noqa: E402


class MergeTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(domains.merge(set(), {}), [])

    def test_new_mail_domain_defaults_disabled(self):
        # DESIGN.md decision #3: "Domains default disabled".
        result = domains.merge({"example.com"}, {})
        self.assertEqual(result, [{"domain": "example.com", "enabled": False, "orphaned": False}])

    def test_enabled_and_present(self):
        result = domains.merge({"example.com"}, {"example.com": {"enabled": True}})
        self.assertEqual(result, [{"domain": "example.com", "enabled": True, "orphaned": False}])

    def test_domain_removed_from_mail_is_orphaned_not_dropped(self):
        # DESIGN.md 4.2: "the stored flag is kept and reported as orphaned
        # in the UI until the administrator removes it."
        result = domains.merge(set(), {"example.com": {"enabled": True}})
        self.assertEqual(result, [{"domain": "example.com", "enabled": True, "orphaned": True}])

    def test_disabled_orphan_stays_disabled(self):
        result = domains.merge(set(), {"example.com": {"enabled": False}})
        self.assertEqual(result, [{"domain": "example.com", "enabled": False, "orphaned": True}])

    def test_sorted_by_domain_and_union_of_both_sources(self):
        result = domains.merge(
            {"b.example.com", "c.example.com"},
            {"a.example.com": {"enabled": True}, "c.example.com": {"enabled": True}},
        )
        self.assertEqual(
            [r["domain"] for r in result],
            ["a.example.com", "b.example.com", "c.example.com"],
        )
        by_domain = {r["domain"]: r for r in result}
        self.assertEqual(by_domain["a.example.com"], {"domain": "a.example.com", "enabled": True, "orphaned": True})
        self.assertEqual(by_domain["b.example.com"], {"domain": "b.example.com", "enabled": False, "orphaned": False})
        self.assertEqual(by_domain["c.example.com"], {"domain": "c.example.com", "enabled": True, "orphaned": False})


class EnabledUsableTests(unittest.TestCase):
    def test_zero_domains(self):
        self.assertEqual(domains.enabled_usable(set(), {}), [])

    def test_one_domain(self):
        result = domains.enabled_usable({"example.com"}, {"example.com": {"enabled": True}})
        self.assertEqual(result, ["example.com"])

    def test_many_domains_sorted(self):
        mail_domains = {"z.example.com", "a.example.com", "m.example.com"}
        state = {d: {"enabled": True} for d in mail_domains}
        self.assertEqual(
            domains.enabled_usable(mail_domains, state),
            ["a.example.com", "m.example.com", "z.example.com"],
        )

    def test_disabled_domain_is_excluded(self):
        result = domains.enabled_usable(
            {"example.com"}, {"example.com": {"enabled": False}}
        )
        self.assertEqual(result, [])

    def test_orphaned_domain_is_excluded_even_if_enabled(self):
        # A domain no longer in mail is dropped from generated config
        # regardless of its stored flag (DESIGN.md 4.2) -- this is exactly
        # what distinguishes enabled_usable() from merge().
        result = domains.enabled_usable(set(), {"example.com": {"enabled": True}})
        self.assertEqual(result, [])

    def test_missing_enabled_key_defaults_false(self):
        result = domains.enabled_usable({"example.com"}, {"example.com": {}})
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()

#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit tests for automx.aliases.build_map() (DESIGN.md 3.3, v2): alias ->
# login from ns8-mail's list-addresses output, in the shape its encoder
# actually writes (a user destination carries "name", not "user").

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "imageroot", "pypkg"))
from automx import aliases  # noqa: E402


def user(login):
    return {"dtype": "user", "name": login, "ui_name": login.title()}


class BuildMapTests(unittest.TestCase):
    def test_domain_alias_to_one_user(self):
        addresses = [{"local": "Dan.Brown", "atype": "domain", "domain": "Example.com", "destinations": [user("dan")]}]
        self.assertEqual(aliases.build_map(addresses, ["example.com"]), {"dan.brown@example.com": "dan"})

    def test_wildcard_alias_applies_to_every_enabled_domain(self):
        addresses = [{"local": "sales", "atype": "wildcard", "destinations": [user("eve")]}]
        self.assertEqual(
            aliases.build_map(addresses, ["a.example", "b.example"]),
            {"sales@a.example": "eve", "sales@b.example": "eve"},
        )

    def test_domain_alias_wins_over_wildcard(self):
        addresses = [
            {"local": "sales", "atype": "wildcard", "destinations": [user("eve")]},
            {"local": "sales", "atype": "domain", "domain": "b.example", "destinations": [user("dan")]},
        ]
        self.assertEqual(
            aliases.build_map(addresses, ["a.example", "b.example"]),
            {"sales@a.example": "eve", "sales@b.example": "dan"},
        )

    def test_disabled_domains_are_left_out(self):
        addresses = [{"local": "sales", "atype": "domain", "domain": "other.example", "destinations": [user("dan")]}]
        self.assertEqual(aliases.build_map(addresses, ["example.com"]), {})

    def test_shared_and_non_user_destinations_are_left_out(self):
        addresses = [
            {"local": "team", "atype": "domain", "domain": "example.com", "destinations": [user("dan"), user("eve")]},
            {"local": "staff", "atype": "domain", "domain": "example.com",
             "destinations": [{"dtype": "group", "name": "staff"}]},
            {"local": "postmaster", "atype": "wildcard", "destinations": [{"dtype": "public", "name": "postmaster"}]},
            {"local": "fwd", "atype": "domain", "domain": "example.com",
             "destinations": [{"dtype": "external", "name": "x@elsewhere.example"}]},
            {"local": "gone", "atype": "domain", "domain": "example.com", "destinations": [{"dtype": "apo", "name": "gone"}]},
        ]
        self.assertEqual(aliases.build_map(addresses, ["example.com"]), {})

    def test_generated_addresses_are_left_to_the_ldap_lookup(self):
        addresses = [
            {"atype": "adduser", "local": "dan", "description": "Dan"},
            {"atype": "addalias", "local": "dan.brown", "domain": "example.com", "destinations": [user("dan")]},
        ]
        self.assertEqual(aliases.build_map(addresses, ["example.com"]), {})


if __name__ == "__main__":
    unittest.main()

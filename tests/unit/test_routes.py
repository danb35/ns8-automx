#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit test for automx.routes.domain_route_exists(), added alongside the
# DNS-before-routes gate (DESIGN.md 5.6, reconcile.py): reconcile_locked()
# relies on this to tell "never had routes yet" apart from "has routes
# already", so the DNS gate applies only to first-time creation.

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "imageroot", "pypkg"))
sys.path.insert(0, HERE)
import stub_agent  # noqa: E402

_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent}):
    from automx import routes  # noqa: E402


class DomainRouteExistsTests(unittest.TestCase):
    def test_true_when_the_route_exists(self):
        with mock.patch.object(routes.agent, "get_route", return_value={"host": "autoconfig.example.com"}):
            self.assertTrue(routes.domain_route_exists("automx1", "example.com"))

    def test_false_when_no_route_exists(self):
        with mock.patch.object(routes.agent, "get_route", return_value=None):
            self.assertFalse(routes.domain_route_exists("automx1", "example.com"))

    def test_checks_the_autoconfig_instance_for_that_domain(self):
        get_route = mock.Mock(return_value=None)
        with mock.patch.object(routes.agent, "get_route", get_route):
            routes.domain_route_exists("automx1", "example.com")
        get_route.assert_called_once_with(routes.instance_name("automx1", "autoconfig", "example.com", 0))


if __name__ == "__main__":
    unittest.main()

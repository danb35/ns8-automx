#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit test for automx.routes.domain_route_exists(), added alongside the
# DNS-before-routes gate (DESIGN.md 5.6, reconcile.py): reconcile_locked()
# relies on this to tell "never had routes yet" apart from "has routes
# already", so the DNS gate applies only to first-time creation.

import io
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


class DeleteRouteWarningTests(unittest.TestCase):
    # Found in audit, 2026-09-24: _delete() (used by delete_domain_routes()
    # and delete_node_autodiscover_route()) used to discard delete-route's
    # result entirely -- every other tasks.run call in this codebase checks
    # exit_code and does something with a failure. Not fatal (a stale route
    # is a smaller problem than aborting disable/removal over it), but it
    # must not be silent either.

    def setUp(self):
        self.tasks_run = mock.Mock()
        self.tasks_patch = mock.patch.object(routes.agent.tasks, "run", self.tasks_run)
        self.tasks_patch.start()
        self.addCleanup(self.tasks_patch.stop)
        self.resolve_patch = mock.patch.object(
            routes.agent, "resolve_agent_id", return_value="traefik@node1"
        )
        self.resolve_patch.start()
        self.addCleanup(self.resolve_patch.stop)

    def test_success_is_silent(self):
        self.tasks_run.return_value = {"exit_code": 0, "output": {}, "error": None}
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            routes._delete("automx1-autoconfig-example.com-0")
        self.assertEqual(stderr.getvalue(), "")

    def test_failure_logs_a_warning_naming_the_instance(self):
        self.tasks_run.return_value = {"exit_code": 1, "output": {}, "error": "not_found"}
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            routes._delete("automx1-autoconfig-example.com-0")
        logged = stderr.getvalue()
        self.assertIn("automx1-autoconfig-example.com-0", logged)
        self.assertIn("not_found", logged)

    def test_delete_domain_routes_attempts_every_instance_even_if_one_fails(self):
        # A failure on one instance must not stop the others from being
        # attempted -- disabling a domain should clean up as much as it can.
        self.tasks_run.return_value = {"exit_code": 1, "output": {}, "error": "boom"}
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            routes.delete_domain_routes("automx1", "example.com")
        expected = len(routes.AUTOCONFIG_PATHS) + 1  # + the autodiscover route
        self.assertEqual(self.tasks_run.call_count, expected)


if __name__ == "__main__":
    unittest.main()

#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Every task this module starts on another agent must be hidden from the
# admin UI's notifications. refresh-aliases calls the mail module every 15
# minutes, and the unhidden calls showed up as a bare "Completed"
# notification each time (found on a real node, 2026-09-29).

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
    from automx import dnshelperclient, mail, node, routes, signing  # noqa: E402

OK = {"exit_code": 0, "output": {}, "error": ""}


class HiddenTaskTests(unittest.TestCase):
    def setUp(self):
        self.run = mock.Mock(return_value=OK)
        # Patch the agent each module actually holds: in a full test run,
        # modules may have been imported first with another test's stub.
        for module in (dnshelperclient, mail, node, routes, signing):
            for patcher in (
                mock.patch.object(module.agent.tasks, "run", self.run),
                mock.patch.object(module.agent, "resolve_agent_id", return_value="module/x1"),
            ):
                patcher.start()
                self.addCleanup(patcher.stop)

    def assert_hidden(self):
        self.assertTrue(self.run.called)
        for call in self.run.call_args_list:
            self.assertEqual(call.kwargs.get("extra"), {"isNotificationHidden": True}, call)

    def test_mail_calls(self):
        mail.get_configuration("mail1")
        mail.list_domains("mail1")
        self.assert_hidden()

    def test_node_fqdn(self):
        self.run.return_value = {"exit_code": 0, "output": {"hostname": "n", "domain": "example.test"}}
        node.get_node_fqdn()
        self.assert_hidden()

    def test_dnshelper_calls(self):
        dnshelperclient._call("module/dnshelper1", "has-zone", {"name": "example.test"})
        self.assert_hidden()

    def test_delete_route(self):
        routes._delete("automx1-autoconfig-example.test-0")
        self.assert_hidden()

    def test_get_certificate(self):
        self.run.return_value = {
            "exit_code": 0,
            "output": {"type": "internal", "certificates": [{"cert": "", "key": ""}]},
        }
        signing.fetch("node.example.test")
        self.assert_hidden()


if __name__ == "__main__":
    unittest.main()

#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# imageroot/bin/refresh-aliases: which domains' aliases go into the map,
# now that resolve_aliases can be set per domain (DESIGN.md 12, 0.4).

import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(REPO_ROOT, "imageroot", "pypkg"))
sys.path.insert(0, HERE)
import stub_agent  # noqa: E402

os.environ.setdefault("AGENT_INSTALL_DIR", os.path.join(REPO_ROOT, "imageroot"))

_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent}):
    _loader = importlib.machinery.SourceFileLoader(
        "refresh_aliases", os.path.join(REPO_ROOT, "imageroot", "bin", "refresh-aliases")
    )
    _spec = importlib.util.spec_from_loader("refresh_aliases", _loader)
    refresh = importlib.util.module_from_spec(_spec)
    _loader.exec_module(refresh)

ADDRESSES = [
    {"local": "fred.flintstone", "atype": "wildcard", "destinations": [{"dtype": "user", "name": "fred"}]},
]


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        patcher = mock.patch.object(refresh.state, "STATE_DIR", self.tmpdir.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def build(self, settings, domains_state):
        refresh.state.save_settings(settings)
        refresh.state.save_domains(domains_state)
        agent = stub_agent.build(
            tasks_run=lambda agent_id, action, data, **kw: {"exit_code": 0, "output": {"addresses": ADDRESSES}},
        )
        info = ("mail1", "mail.example", "ad.example", {"a.example", "b.example"})
        with mock.patch.object(refresh, "agent", agent), \
                mock.patch.object(refresh.mail, "get_instance_info", return_value=info):
            return refresh.build(), agent

    def test_default_on_maps_every_enabled_domain(self):
        alias_map, _agent = self.build({}, {"a.example": {"enabled": True}, "b.example": {"enabled": True}})
        self.assertEqual(alias_map, {"fred.flintstone@a.example": "fred", "fred.flintstone@b.example": "fred"})

    def test_domain_turned_off_is_left_out(self):
        alias_map, _agent = self.build(
            {},
            {"a.example": {"enabled": True}, "b.example": {"enabled": True, "overrides": {"resolve_aliases": False}}},
        )
        self.assertEqual(alias_map, {"fred.flintstone@a.example": "fred"})

    def test_domain_turned_on_with_the_default_off(self):
        alias_map, _agent = self.build(
            {"resolve_aliases": False},
            {"a.example": {"enabled": True}, "b.example": {"enabled": True, "overrides": {"resolve_aliases": True}}},
        )
        self.assertEqual(alias_map, {"fred.flintstone@b.example": "fred"})

    def test_all_off_asks_the_mail_module_nothing(self):
        alias_map, agent = self.build({"resolve_aliases": False}, {"a.example": {"enabled": True}})
        self.assertEqual(alias_map, {})
        agent.tasks.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

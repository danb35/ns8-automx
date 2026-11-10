#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# imageroot/actions/set-domain-settings/10apply (DESIGN.md 12, 0.4): which
# domains and groupware choices it refuses, and how it stores overrides.

import importlib.machinery
import importlib.util
import io
import json
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

_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent}):
    from automx import groupware, mail, reconcile, state  # noqa: E402

for _mod, _name in (
    (groupware, "automx.groupware"),
    (mail, "automx.mail"),
    (reconcile, "automx.reconcile"),
    (state, "automx.state"),
):
    sys.modules[_name] = _mod

ACTION_PATH = os.path.join(REPO_ROOT, "imageroot", "actions", "set-domain-settings", "10apply")
CANDIDATES = [
    {"module_id": "sogo1", "dav_url": "https://s/SOGo/dav/", "activesync_url": "https://s/as"},
    {"module_id": "nextcloud1", "dav_url": "https://n/remote.php/dav/", "activesync_url": None},
]


class SetDomainSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        patcher = mock.patch.object(state, "STATE_DIR", self.tmpdir.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        state.save_settings({})
        state.save_domains(
            {
                "a.example": {"enabled": True},
                "gone.example": {"enabled": True, "overrides": {"display_names": False}},
            }
        )

    def run_action(self, data, mail_domains=("a.example", "b.example")):
        env = {"MODULE_ID": "automx1", "AGENT_INSTALL_DIR": os.path.join(REPO_ROOT, "imageroot")}
        self.reconcile = mock.Mock()
        fake_agent = stub_agent.build()
        info = ("mail1", "mail.example", "ad.example", set(mail_domains))
        with mock.patch.object(mail, "get_instance_info", return_value=info), \
                mock.patch.object(groupware, "list_candidates", return_value=list(CANDIDATES)), \
                mock.patch.object(reconcile, "lock", mock.MagicMock()), \
                mock.patch.object(reconcile, "reconcile_locked", self.reconcile), \
                mock.patch.dict(sys.modules, {"agent": fake_agent}), \
                mock.patch.dict(os.environ, env, clear=False), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(data))), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            loader = importlib.machinery.SourceFileLoader("set_domain_settings_10apply", ACTION_PATH)
            spec = importlib.util.spec_from_loader(loader.name, loader)
            module = importlib.util.module_from_spec(spec)
            code = 0
            try:
                loader.exec_module(module)
            except SystemExit as exc:
                code = exc.code
            self.output = json.loads(stdout.getvalue())
        return code, fake_agent

    def test_overrides_are_stored_and_applied(self):
        code, _agent = self.run_action(
            {"domain": "a.example", "overrides": {"display_names": False, "dav_module": "sogo1"}}
        )
        self.assertEqual(code, 0)
        entry = state.load_domains()["a.example"]
        self.assertEqual(entry, {"enabled": True, "overrides": {"display_names": False, "dav_module": "sogo1"}})
        self.reconcile.assert_called_once()
        self.assertEqual(self.output["overrides"], {"display_names": False, "dav_module": "sogo1"})
        self.assertEqual(
            self.output["settings"],
            {"display_names": False, "resolve_aliases": True, "dav_module": "sogo1", "activesync_module": None},
        )

    def test_overrides_replace_the_previous_ones(self):
        self.run_action({"domain": "a.example", "overrides": {"display_names": False, "dav_module": "sogo1"}})
        self.run_action({"domain": "a.example", "overrides": {"resolve_aliases": False}})
        self.assertEqual(state.load_domains()["a.example"]["overrides"], {"resolve_aliases": False})

    def test_empty_overrides_go_back_to_the_defaults(self):
        self.run_action({"domain": "gone.example", "overrides": {}})
        self.assertEqual(state.load_domains()["gone.example"], {"enabled": True})

    def test_none_for_a_domain_is_stored_as_null(self):
        state.save_settings({"dav_module": "sogo1"})
        self.run_action({"domain": "a.example", "overrides": {"dav_module": None}})
        self.assertIsNone(self.output["settings"]["dav_module"])
        self.assertIn("dav_module", state.load_domains()["a.example"]["overrides"])

    def test_mail_domain_never_enabled_gets_a_disabled_entry(self):
        code, _agent = self.run_action({"domain": "b.example", "overrides": {"display_names": False}})
        self.assertEqual(code, 0)
        self.assertEqual(
            state.load_domains()["b.example"], {"enabled": False, "overrides": {"display_names": False}}
        )

    def test_orphan_can_be_changed(self):
        code, _agent = self.run_action({"domain": "gone.example", "overrides": {"resolve_aliases": False}})
        self.assertEqual(code, 0)

    def test_unknown_domain_is_refused(self):
        code, fake_agent = self.run_action({"domain": "other.example", "overrides": {}})
        self.assertEqual(code, 3)
        self.assertEqual(self.output[0]["error"], "domain_not_found")
        self.assertNotIn("other.example", state.load_domains())
        self.reconcile.assert_not_called()

    def test_groupware_that_does_not_provide_the_service_is_refused(self):
        code, _agent = self.run_action(
            {"domain": "a.example", "overrides": {"activesync_module": "nextcloud1"}}
        )
        self.assertEqual(code, 3)
        self.assertEqual(self.output[0]["parameter"], "activesync_module")
        self.assertEqual(self.output[0]["error"], "groupware_not_available")
        self.assertNotIn("overrides", state.load_domains()["a.example"])


if __name__ == "__main__":
    unittest.main()

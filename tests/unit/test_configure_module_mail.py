#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# imageroot/actions/configure-module/10save, the mail server part (DESIGN.md
# decision #15): what it refuses, when it binds, and which routes a change
# of mail server removes.

import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(REPO_ROOT, "imageroot", "pypkg"))
sys.path.insert(0, HERE)
import stub_agent  # noqa: E402

_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent}):
    from automx import groupware, mail, reconcile, routes, state  # noqa: E402

for _mod, _name in (
    (groupware, "automx.groupware"),
    (mail, "automx.mail"),
    (reconcile, "automx.reconcile"),
    (routes, "automx.routes"),
    (state, "automx.state"),
):
    sys.modules[_name] = _mod

ACTION_PATH = os.path.join(REPO_ROOT, "imageroot", "actions", "configure-module", "10save")
INFO = {
    "uuid-a": ("mail1", "mail.a.example", "a.example", {"a.example", "shared.example"}),
    "uuid-b": ("mail2", "mail.b.example", "b.example", {"b.example", "shared.example"}),
}
DOMAINS = {
    "a.example": {"enabled": True},
    "shared.example": {"enabled": True},
    "off.example": {"enabled": False},
}


def get_instance_info(rdb, module_uuid=None):
    if module_uuid == "uuid-raw":
        raise mail.MailNotConfigured()
    if module_uuid not in INFO:
        raise mail.MailNotFound()
    return INFO[module_uuid]


class SaveTests(unittest.TestCase):
    def run_action(self, data, bound=None, current=None, users=None, candidates=()):
        env = {"MODULE_ID": "automx1", "AGENT_INSTALL_DIR": os.path.join(REPO_ROOT, "imageroot")}
        if bound:
            env["MAIL_SERVER"] = bound
        self.save_settings = mock.Mock()
        self.bind = mock.Mock()
        self.delete_routes = mock.Mock()
        fake_agent = stub_agent.build()
        with mock.patch.object(state, "load_settings", return_value=dict(state.DEFAULT_SETTINGS)), \
                mock.patch.object(state, "save_settings", self.save_settings), \
                mock.patch.object(state, "load_domains", return_value=DOMAINS), \
                mock.patch.object(mail, "bind", self.bind), \
                mock.patch.object(mail, "current_uuid", return_value=current or bound), \
                mock.patch.object(mail, "get_instance_info", side_effect=get_instance_info), \
                mock.patch.object(mail, "users_of", return_value=users or {}), \
                mock.patch.object(groupware, "list_candidates", return_value=list(candidates)), \
                mock.patch.object(routes, "delete_domain_routes", self.delete_routes), \
                mock.patch.object(reconcile, "lock", mock.MagicMock()), \
                mock.patch.dict(sys.modules, {"agent": fake_agent}), \
                mock.patch.dict(os.environ, env, clear=False), \
                mock.patch("json.load", return_value=data), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            if not bound:
                os.environ.pop("MAIL_SERVER", None)
            loader = importlib.machinery.SourceFileLoader("configure_module_10save", ACTION_PATH)
            spec = importlib.util.spec_from_loader(loader.name, loader)
            module = importlib.util.module_from_spec(spec)
            try:
                loader.exec_module(module)
            except SystemExit as exc:
                self.output = json.loads(stdout.getvalue())
                return exc.code, fake_agent
        return 0, fake_agent

    def test_saving_other_settings_leaves_the_binding_alone(self):
        code, _ = self.run_action({"http2https": False}, bound="uuid-a")
        self.assertEqual(code, 0)
        self.save_settings.assert_called_once()
        self.bind.assert_not_called()

    def test_saving_the_bound_server_skips_the_in_use_check(self):
        # Two instances can already share one (a clone); saving must still work.
        code, _ = self.run_action({"mail_server": "uuid-a"}, bound="uuid-a", users={"uuid-a": "automx2"})
        self.assertEqual(code, 0)
        self.bind.assert_not_called()

    def test_unknown_server_is_refused_and_nothing_saved(self):
        code, agent = self.run_action({"mail_server": "uuid-gone"}, bound="uuid-a")
        self.assertEqual(code, 3)
        self.assertEqual(agent.status_calls, ["validation-failed"])
        self.save_settings.assert_not_called()
        self.bind.assert_not_called()

    def test_server_used_by_another_instance_is_refused(self):
        code, _ = self.run_action({"mail_server": "uuid-b"}, bound="uuid-a", users={"uuid-b": "automx2"})
        self.assertEqual(code, 3)
        self.assertEqual(self.output[0]["error"], "mail_server_in_use")
        self.bind.assert_not_called()
        self.delete_routes.assert_not_called()

    def test_unconfigured_server_has_its_own_error(self):
        code, _ = self.run_action({"mail_server": "uuid-raw"}, bound="uuid-a")
        self.assertEqual(code, 3)
        self.assertEqual(self.output[0]["error"], "mail_server_not_configured")
        self.bind.assert_not_called()

    def test_unbound_with_every_server_taken_still_saves_other_settings(self):
        # The page sends no mail_server when there is no default to show.
        code, _ = self.run_action({"http2https": False}, current=None, users={"uuid-a": "automx2", "uuid-b": "automx3"})
        self.assertEqual(code, 0)
        self.save_settings.assert_called_once()
        self.bind.assert_not_called()

    def test_first_choice_of_the_default_binds_and_removes_nothing(self):
        code, _ = self.run_action({"mail_server": "uuid-a"}, current="uuid-a")
        self.assertEqual(code, 0)
        self.bind.assert_called_once_with("uuid-a")
        self.delete_routes.assert_not_called()

    def test_change_removes_routes_of_enabled_domains_the_new_server_lacks(self):
        code, _ = self.run_action({"mail_server": "uuid-b"}, bound="uuid-a")
        self.assertEqual(code, 0)
        self.bind.assert_called_once_with("uuid-b")
        self.delete_routes.assert_called_once_with("automx1", "a.example")

    def test_groupware_is_checked_against_the_new_server(self):
        code, _ = self.run_action({"mail_server": "uuid-b", "dav_module": "sogo1"}, bound="uuid-a")
        self.assertEqual(code, 3)
        self.bind.assert_not_called()
        self.save_settings.assert_not_called()

        code, _ = self.run_action(
            {"mail_server": "uuid-b", "dav_module": "sogo1"},
            bound="uuid-a",
            candidates=[{"module_id": "sogo1", "dav_url": "https://sogo/dav", "activesync_url": None}],
        )
        self.assertEqual(code, 0)
        self.bind.assert_called_once_with("uuid-b")


if __name__ == "__main__":
    unittest.main()

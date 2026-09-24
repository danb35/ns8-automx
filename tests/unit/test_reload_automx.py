#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# reload-automx must be idempotent: a reconcile that renders the same config
# the running service already has must not restart it. Found on a real node,
# 2026-09-24 -- the module's own first user-domain bind publishes
# module-domain-changed to itself, whose handler reconciles, and that used to
# bounce the service a second time right after set-domains returned.

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, HERE)
import stub_agent  # noqa: E402

_STATE = tempfile.TemporaryDirectory()
os.environ["AGENT_STATE_DIR"] = _STATE.name
os.environ["AGENT_INSTALL_DIR"] = os.path.join(REPO_ROOT, "imageroot")
os.environ["AUTOMX_APP_IMAGE"] = "localhost/automx-app:test"

_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent}):
    _loader = importlib.machinery.SourceFileLoader(
        "reload_automx", os.path.join(REPO_ROOT, "imageroot", "bin", "reload-automx")
    )
    _spec = importlib.util.spec_from_loader("reload_automx", _loader)
    reload_automx = importlib.util.module_from_spec(_spec)
    _loader.exec_module(reload_automx)


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


class ReloadIdempotenceTests(unittest.TestCase):
    def setUp(self):
        self.conf = reload_automx.AUTOMX_CONF_PATH
        self.lookup = reload_automx.LDAP_LOOKUP_PATH
        self.calls = []
        self.service_active = True

        def run_helper(*args, **kwargs):
            self.calls.append(args)
            if args[:3] == ("systemctl", "--user", "is-active"):
                return SimpleNamespace(returncode=0 if self.service_active else 3, check_returncode=lambda: None)
            return SimpleNamespace(returncode=0, check_returncode=lambda: None)

        patches = [
            mock.patch.object(reload_automx.agent, "run_helper", side_effect=run_helper),
            mock.patch.object(
                reload_automx,
                "run_render",
                return_value=SimpleNamespace(returncode=0, stdout='["example.com"]', stderr=""),
            ),
            mock.patch.object(
                reload_automx, "run_validate", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.remove_files)

    def remove_files(self):
        for base in (self.conf, self.lookup):
            for path in (base, base + reload_automx.STAGING_SUFFIX):
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass

    def install(self, conf, lookup, staged_conf, staged_lookup):
        write(self.conf, conf)
        write(self.lookup, lookup)
        write(self.conf + reload_automx.STAGING_SUFFIX, staged_conf)
        write(self.lookup + reload_automx.STAGING_SUFFIX, staged_lookup)

    def restarted(self):
        return any(c[:3] == ("systemctl", "--user", "restart") for c in self.calls)

    def test_identical_render_and_active_service_does_not_restart(self):
        self.install("conf", "lookup", "conf", "lookup")
        self.assertEqual(reload_automx.main(), 0)
        self.assertFalse(self.restarted())
        reload_automx.run_validate.assert_not_called()
        # the staged copies are cleaned up, not left behind
        self.assertFalse(os.path.exists(self.conf + reload_automx.STAGING_SUFFIX))
        self.assertFalse(os.path.exists(self.lookup + reload_automx.STAGING_SUFFIX))

    def test_changed_conf_restarts(self):
        self.install("conf", "lookup", "conf CHANGED", "lookup")
        self.assertEqual(reload_automx.main(), 0)
        self.assertTrue(self.restarted())
        with open(self.conf) as f:
            self.assertEqual(f.read(), "conf CHANGED")

    def test_changed_lookup_restarts(self):
        # the LDAP connection parameters live in the lookup file, not the conf
        self.install("conf", "lookup", "conf", "lookup CHANGED")
        self.assertEqual(reload_automx.main(), 0)
        self.assertTrue(self.restarted())

    def test_identical_render_but_inactive_service_starts_it(self):
        self.service_active = False
        self.install("conf", "lookup", "conf", "lookup")
        self.assertEqual(reload_automx.main(), 0)
        self.assertTrue(self.restarted())

    def test_first_ever_render_has_nothing_installed_and_starts(self):
        write(self.conf + reload_automx.STAGING_SUFFIX, "conf")
        write(self.lookup + reload_automx.STAGING_SUFFIX, "lookup")
        self.assertEqual(reload_automx.main(), 0)
        self.assertTrue(self.restarted())


if __name__ == "__main__":
    unittest.main()

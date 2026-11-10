#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# automx.state settings defaults: alias resolution (added in 0.2.0) is on
# for new installs but stays off for instances from before it existed, so
# updating from 0.1.x doesn't change what they hand out.

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "imageroot", "pypkg"))
from automx import state  # noqa: E402


class SettingsDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        patcher = mock.patch.object(state, "STATE_DIR", self.tmpdir.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = os.path.join(self.tmpdir.name, "settings.json")

    def write(self, settings):
        with open(self.path, "w") as f:
            json.dump(settings, f)

    def test_new_install_resolves_aliases(self):
        # create-module writes every default.
        state.save_settings({})
        self.assertTrue(state.load_settings()["resolve_aliases"])
        with open(self.path) as f:
            self.assertIs(json.load(f)["resolve_aliases"], True)

    def test_settings_from_0_1_keep_aliases_off(self):
        # 0.1.x's settings.json, as its create-module wrote it.
        self.write({"service_host": None, "http2https": True, "display_names": True})
        settings = state.load_settings()
        self.assertFalse(settings["resolve_aliases"])
        self.assertTrue(settings["display_names"])

    def test_saving_old_settings_keeps_aliases_off(self):
        # configure-module loads, updates and saves: the upgrade default is
        # then stored, and stays put.
        self.write({"service_host": None, "http2https": True, "display_names": True})
        settings = state.load_settings()
        settings["http2https"] = False
        state.save_settings(settings)
        with open(self.path) as f:
            self.assertIs(json.load(f)["resolve_aliases"], False)
        self.assertFalse(state.load_settings()["resolve_aliases"])

    def test_explicit_choice_wins(self):
        self.write({"display_names": True, "resolve_aliases": True})
        self.assertTrue(state.load_settings()["resolve_aliases"])
        self.write({"display_names": True, "resolve_aliases": False})
        self.assertFalse(state.load_settings()["resolve_aliases"])

    def test_no_settings_file_uses_the_install_defaults(self):
        self.assertTrue(state.load_settings()["resolve_aliases"])


class PerDomainSettingsTests(unittest.TestCase):
    # DESIGN.md 12, 0.4: a domain's overrides on top of the instance-wide
    # defaults.

    SETTINGS = dict(state.DEFAULT_SETTINGS, dav_module="sogo1", display_names=True)

    def test_entry_without_overrides_follows_the_defaults(self):
        # Every entry written before 0.4.
        self.assertEqual(
            state.effective_settings(self.SETTINGS, {"enabled": True}),
            {"display_names": True, "resolve_aliases": True, "dav_module": "sogo1", "activesync_module": None},
        )

    def test_missing_entry_follows_the_defaults(self):
        self.assertEqual(state.effective_settings(self.SETTINGS, None)["dav_module"], "sogo1")

    def test_override_wins_and_null_means_none(self):
        effective = state.effective_settings(
            self.SETTINGS, {"enabled": True, "overrides": {"display_names": False, "dav_module": None}}
        )
        self.assertFalse(effective["display_names"])
        self.assertIsNone(effective["dav_module"])
        self.assertTrue(effective["resolve_aliases"])

    def test_only_per_domain_settings_can_be_overridden(self):
        flags = {"overrides": {"service_host": "x.example", "sign_profiles": True, "resolve_aliases": False}}
        self.assertEqual(state.domain_overrides(flags), {"resolve_aliases": False})
        self.assertNotIn("service_host", state.effective_settings(self.SETTINGS, flags))


if __name__ == "__main__":
    unittest.main()

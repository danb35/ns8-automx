#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit tests for imageroot/bin/automx-ldap-lookup -- the automx script
# backend's LDAP lookup and, more importantly, its always-exit-0 fallback
# contract (DESIGN.md 3.3). Runs INSIDE the automx-app container in
# production and never imports "agent"; here it's loaded directly (no .py
# extension, via importlib) with a fake "ldap" module injected, since
# python-ldap isn't assumed to be installed wherever these tests run.
#
# DESIGN.md 9.1 asks for "renderer golden files for OpenLDAP and AD" --
# the schema-specific attribute mapping actually lives here (ATTR_MAP), not
# in the renderer, which just passes the schema string through untouched.

import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(HERE, "..", "..")


def load_module_fresh():
    """A fresh import each time: main()/lookup() close over CONFIG_PATH at
    module level via os.environ, and tests use a per-test temp file."""
    loader = importlib.machinery.SourceFileLoader(
        "automx_ldap_lookup", os.path.join(REPO_ROOT, "imageroot", "bin", "automx-ldap-lookup")
    )
    spec = importlib.util.spec_from_loader("automx_ldap_lookup", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FakeConnection:
    """Stands in for what ldap.initialize() returns. bind_error and
    search_results are set per test; captures the exact filter/base/scope
    search_s() was called with."""

    def __init__(self, bind_error=None, search_results=None):
        self.bind_error = bind_error
        self.search_results = search_results if search_results is not None else []
        self.search_calls = []
        self.unbound = False

    def set_option(self, *args):
        pass

    def simple_bind_s(self, bind_dn, bind_password):
        if self.bind_error:
            raise self.bind_error

    def search_s(self, base_dn, scope, search_filter, attrs):
        self.search_calls.append({"base_dn": base_dn, "scope": scope, "filter": search_filter, "attrs": attrs})
        return self.search_results

    def unbind_s(self):
        self.unbound = True


def fake_ldap_module(connection):
    ldap = types.ModuleType("ldap")
    ldap.SCOPE_SUBTREE = 2
    ldap.OPT_NETWORK_TIMEOUT = 1
    ldap.OPT_TIMEOUT = 2
    ldap.OPT_REFERRALS = 3
    ldap.initialize = mock.Mock(return_value=connection)

    ldap_filter = types.ModuleType("ldap.filter")
    # A real-enough escape for tests: same identity behavior as
    # python-ldap's own for the plain inputs used here (no special chars).
    ldap_filter.escape_filter_chars = lambda s: s
    ldap.filter = ldap_filter
    return ldap


def _remove_if_present(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass  # test_missing_config_file_falls_back removes it itself


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.config_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        self.config_file.close()
        self.addCleanup(_remove_if_present, self.config_file.name)
        self.env_patch = mock.patch.dict(os.environ, {"AUTOMX_LDAP_LOOKUP_CONFIG": self.config_file.name})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def write_config(self, **overrides):
        config = {
            "host": "10.0.2.2",
            "port": 3890,
            "bind_dn": "cn=automx,dc=example,dc=com",
            "bind_password": "secret",
            "base_dn": "dc=example,dc=com",
            "schema": "rfc2307",
            "hidden_users_filter": "",
        }
        config.update(overrides)
        with open(self.config_file.name, "w") as f:
            json.dump(config, f)
        return config

    def run_lookup(self, connection, argv):
        module = load_module_fresh()
        ldap = fake_ldap_module(connection)
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"ldap": ldap, "ldap.filter": ldap.filter}), \
                mock.patch.object(sys, "argv", ["automx-ldap-lookup", *argv]), \
                mock.patch.object(sys, "stdout", out):
            module.main()  # never calls sys.exit() on any path (DESIGN.md 3.3)
        return out.getvalue(), module

    # -- rfc2307 (OpenLDAP) --

    def test_rfc2307_match_by_login_attribute(self):
        self.write_config(schema="rfc2307")
        conn = FakeConnection(search_results=[("uid=dan,dc=example,dc=com", {"uid": [b"dan"], "cn": [b"Dan Brown"]})])
        out, _ = self.run_lookup(conn, ["dan", "example.com", "dan@example.com"])
        self.assertEqual(out, "dan|Dan Brown\n")
        self.assertEqual(conn.search_calls[0]["filter"], "(&(|(uid=dan)(mail=dan@example.com)))")
        self.assertEqual(conn.search_calls[0]["attrs"], ["uid", "cn"])
        self.assertTrue(conn.unbound)

    def test_rfc2307_match_by_mail_attribute_for_an_alias(self):
        # DESIGN.md 3.3 lookup rule, second step: mail attribute matches
        # the full address even though the local part isn't the login.
        self.write_config(schema="rfc2307")
        conn = FakeConnection(
            search_results=[("uid=dan,dc=example,dc=com", {"uid": [b"dan"], "cn": [b"Dan Brown"]})]
        )
        out, _ = self.run_lookup(conn, ["dan.brown", "example.com", "dan.brown@example.com"])
        self.assertEqual(out, "dan|Dan Brown\n")

    # -- ad (Samba AD) --

    def test_ad_schema_uses_samaccountname_and_displayname(self):
        self.write_config(schema="ad")
        conn = FakeConnection(
            search_results=[
                ("cn=dan,dc=ad,dc=example,dc=com", {"sAMAccountName": [b"dan"], "displayName": [b"Dan Brown"]})
            ]
        )
        out, _ = self.run_lookup(conn, ["dan", "example.com", "dan@example.com"])
        self.assertEqual(out, "dan|Dan Brown\n")
        self.assertEqual(
            conn.search_calls[0]["filter"], "(&(|(sAMAccountName=dan)(mail=dan@example.com)))"
        )
        self.assertEqual(conn.search_calls[0]["attrs"], ["sAMAccountName", "displayName"])

    def test_hidden_users_filter_is_anded_in(self):
        self.write_config(schema="rfc2307", hidden_users_filter="(!(nsAccountLock=true))")
        conn = FakeConnection(search_results=[])
        self.run_lookup(conn, ["dan", "example.com", "dan@example.com"])
        self.assertEqual(
            conn.search_calls[0]["filter"],
            "(&(|(uid=dan)(mail=dan@example.com))(!(nsAccountLock=true)))",
        )

    # -- fallback contract (DESIGN.md 3.3): always exit 0, always one line --

    def test_no_match_falls_back_to_bare_address(self):
        self.write_config()
        conn = FakeConnection(search_results=[])
        out, _ = self.run_lookup(conn, ["dan", "example.com", "dan@example.com"])
        self.assertEqual(out, "dan@example.com|\n")

    def test_bind_failure_falls_back(self):
        self.write_config()
        conn = FakeConnection(bind_error=Exception("connection refused"))
        out, _ = self.run_lookup(conn, ["dan", "example.com", "dan@example.com"])
        self.assertEqual(out, "dan@example.com|\n")

    def test_missing_config_file_falls_back(self):
        os.remove(self.config_file.name)
        conn = FakeConnection()
        out, _ = self.run_lookup(conn, ["dan", "example.com", "dan@example.com"])
        self.assertEqual(out, "dan@example.com|\n")

    def test_entry_with_no_login_value_is_skipped_then_falls_back(self):
        self.write_config()
        conn = FakeConnection(search_results=[("dn", {"cn": [b"Dan Brown"]})])  # no "uid"
        out, _ = self.run_lookup(conn, ["dan", "example.com", "dan@example.com"])
        self.assertEqual(out, "dan@example.com|\n")

    def test_missing_ldap_module_falls_back(self):
        # Real-world equivalent: python-ldap somehow isn't importable in the
        # container. main() must not propagate the ImportError.
        module = load_module_fresh()
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"ldap": None}), \
                mock.patch.object(sys, "argv", ["automx-ldap-lookup", "dan", "example.com", "dan@example.com"]), \
                mock.patch.object(sys, "stdout", out):
            module.main()
        self.assertEqual(out.getvalue(), "dan@example.com|\n")

    def test_display_name_with_pipe_is_stripped_not_left_to_break_the_separator(self):
        self.write_config()
        conn = FakeConnection(
            search_results=[("dn", {"uid": [b"dan"], "cn": [b"Dan | Brown"]})]
        )
        out, _ = self.run_lookup(conn, ["dan", "example.com", "dan@example.com"])
        self.assertEqual(out, "dan|Dan  Brown\n")

    def test_wrong_argv_count_falls_back_without_crashing(self):
        module = load_module_fresh()
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["automx-ldap-lookup", "only-one-arg"]), \
                mock.patch.object(sys, "stdout", out):
            module.main()
        self.assertEqual(out.getvalue(), "only-one-arg|\n")

    def test_no_argv_at_all_falls_back_without_crashing(self):
        module = load_module_fresh()
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["automx-ldap-lookup"]), \
                mock.patch.object(sys, "stdout", out):
            module.main()
        self.assertEqual(out.getvalue(), "|\n")


if __name__ == "__main__":
    unittest.main()

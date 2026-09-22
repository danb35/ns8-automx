#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Golden-file-style tests for imageroot/bin/render-automx-conf (DESIGN.md
# 9.1: "renderer golden files for OpenLDAP and AD, zero/one/many domains,
# quoting of odd input"). It's a bin/ script with no .py extension, loaded
# here via importlib.machinery.SourceFileLoader; "agent" (and everything
# it pulls in via imageroot/pypkg) is stubbed first since it only exists
# for real on an NS8 node.

import configparser
import importlib.machinery
import importlib.util
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

os.environ.setdefault("AGENT_INSTALL_DIR", os.path.join(REPO_ROOT, "imageroot"))

_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent, "agent.ldapproxy": _agent.ldapproxy}):
    _loader = importlib.machinery.SourceFileLoader(
        "render_automx_conf", os.path.join(REPO_ROOT, "imageroot", "bin", "render-automx-conf")
    )
    _spec = importlib.util.spec_from_loader("render_automx_conf", _loader)
    render = importlib.util.module_from_spec(_spec)
    _loader.exec_module(render)


def read_ini(path):
    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str
    config.read(path)
    return config


class WriteAutomxConfTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = os.path.join(self.tmpdir.name, "automx.conf")

    def test_one_domain(self):
        render.write_automx_conf(self.path, "node.example.net", ["example.com"], "mail.example.com", True)
        config = read_ini(self.path)
        self.assertEqual(config["automx"]["provider"], "node.example.net")
        self.assertEqual(config["automx"]["domains"], "example.com")
        self.assertEqual(config["automx"]["autodiscover_v2"], "no")
        self.assertEqual(config["global"]["backend"], "script")
        self.assertEqual(
            config["global"]["script"], "/usr/local/bin/automx-ldap-lookup %u %d %s"
        )
        self.assertEqual(config["global"]["result_attrs"], "login display_name")
        self.assertEqual(config["global"]["separator"], "|")
        self.assertEqual(config["global"]["imap_server"], "mail.example.com")
        self.assertEqual(config["global"]["imap_port"], "993")
        self.assertEqual(config["global"]["imap_encryption"], "ssl")
        self.assertEqual(config["global"]["imap_auth_identity"], "${login}")
        self.assertEqual(config["global"]["smtp_server"], "mail.example.com")
        self.assertEqual(config["global"]["smtp_port"], "465")
        self.assertEqual(config["global"]["smtp_auth_identity"], "${login}")

    def test_many_domains_comma_separated(self):
        render.write_automx_conf(
            self.path,
            "node.example.net",
            ["a.example.com", "b.example.com", "c.example.com"],
            "mail.example.com",
            True,
        )
        config = read_ini(self.path)
        self.assertEqual(config["automx"]["domains"], "a.example.com, b.example.com, c.example.com")

    def test_display_names_on_sets_account_name(self):
        render.write_automx_conf(self.path, "node.example.net", ["example.com"], "mail.example.com", True)
        config = read_ini(self.path)
        self.assertEqual(config["global"]["account_name"], "${display_name}")
        self.assertEqual(config["global"]["account_name_short"], "${display_name}")

    def test_display_names_off_omits_account_name(self):
        # DESIGN.md 8: the setting is off by an admin trading client UX for
        # less unauthenticated disclosure -- must actually be absent, not
        # just empty, since an empty value would still surface something.
        render.write_automx_conf(self.path, "node.example.net", ["example.com"], "mail.example.com", False)
        config = read_ini(self.path)
        self.assertNotIn("account_name", config["global"])
        self.assertNotIn("account_name_short", config["global"])

    def test_literal_percent_in_script_line_survives_configparser(self):
        # Regression test for the interpolation=None fix: automx's own
        # %u/%d/%s macros in the script line are not configparser
        # interpolation syntax, and a naive ConfigParser would raise
        # InterpolationSyntaxError trying to write them.
        render.write_automx_conf(self.path, "node.example.net", ["example.com"], "mail.example.com", True)
        with open(self.path) as f:
            raw = f.read()
        self.assertIn("script = /usr/local/bin/automx-ldap-lookup %u %d %s", raw)

    def test_idn_hostname_round_trips(self):
        render.write_automx_conf(self.path, "xn--nnx388a.example.net", ["xn--nnx388a.example.com"], "mail.example.com", True)
        config = read_ini(self.path)
        self.assertEqual(config["automx"]["provider"], "xn--nnx388a.example.net")
        self.assertEqual(config["automx"]["domains"], "xn--nnx388a.example.com")

    def test_file_mode_is_not_world_readable(self):
        render.write_automx_conf(self.path, "node.example.net", ["example.com"], "mail.example.com", True)
        mode = os.stat(self.path).st_mode & 0o777
        self.assertEqual(mode, 0o640)


class WriteLdapLookupTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = os.path.join(self.tmpdir.name, "ldap-lookup.json")

    def read(self):
        with open(self.path) as f:
            return json.load(f)

    def test_rfc2307_schema_passthrough(self):
        ldap_domain = {
            "host": "127.0.0.1",
            "port": 3890,
            "bind_dn": "cn=automx,dc=example,dc=com",
            "bind_password": "secret",
            "base_dn": "dc=example,dc=com",
            "schema": "rfc2307",
        }
        render.write_ldap_lookup(self.path, ldap_domain, "(!(nsAccountLock=true))")
        written = self.read()
        self.assertEqual(written["schema"], "rfc2307")
        self.assertEqual(written["base_dn"], "dc=example,dc=com")
        self.assertEqual(written["hidden_users_filter"], "(!(nsAccountLock=true))")

    def test_ad_schema_passthrough(self):
        ldap_domain = {
            "host": "127.0.0.1",
            "port": 3890,
            "bind_dn": "cn=automx,dc=ad,dc=example,dc=com",
            "bind_password": "secret",
            "base_dn": "dc=ad,dc=example,dc=com",
            "schema": "ad",
        }
        render.write_ldap_lookup(self.path, ldap_domain, "")
        written = self.read()
        self.assertEqual(written["schema"], "ad")
        self.assertEqual(written["hidden_users_filter"], "")

    def test_host_translated_for_container_network(self):
        # DESIGN.md 3.3/4.1: the container reaches ldapproxy at 10.0.2.2,
        # not 127.0.0.1 (the host's own view of ldapproxy's listener).
        ldap_domain = {
            "host": "127.0.0.1",
            "port": 3890,
            "bind_dn": "x",
            "bind_password": "x",
            "base_dn": "x",
            "schema": "rfc2307",
        }
        render.write_ldap_lookup(self.path, ldap_domain, "")
        self.assertEqual(self.read()["host"], render.CONTAINER_HOST_LOOPBACK)

    def test_non_loopback_host_is_left_alone(self):
        ldap_domain = {
            "host": "10.1.2.3",
            "port": 3890,
            "bind_dn": "x",
            "bind_password": "x",
            "base_dn": "x",
            "schema": "rfc2307",
        }
        render.write_ldap_lookup(self.path, ldap_domain, "")
        self.assertEqual(self.read()["host"], "10.1.2.3")

    def test_file_mode_is_owner_only(self):
        # Contains the LDAP bind password -- DESIGN.md 3.3/4.2.
        ldap_domain = {
            "host": "127.0.0.1", "port": 1, "bind_dn": "x",
            "bind_password": "secret", "base_dn": "x", "schema": "rfc2307",
        }
        render.write_ldap_lookup(self.path, ldap_domain, "")
        mode = os.stat(self.path).st_mode & 0o777
        self.assertEqual(mode, 0o600)


class MainOrchestrationTests(unittest.TestCase):
    """Exercises main() end to end through the stub agent, for the
    zero-domains and no-mail-module paths (DESIGN.md 4.3)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.state_patch = mock.patch.object(render.state, "STATE_DIR", self.tmpdir.name)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.argv_patch = mock.patch.object(sys, "argv", ["render-automx-conf"])
        self.argv_patch.start()
        self.addCleanup(self.argv_patch.stop)

    def run_main_expecting_exit(self, code):
        with self.assertRaises(SystemExit) as cm:
            render.main()
        self.assertEqual(cm.exception.code, code)

    def test_no_mail_module_exits_nonzero_and_clears_state(self):
        # Pre-create stale rendered files, as if a mail instance existed at
        # the last render and has since been removed -- proves
        # clear_rendered_state() actually removes them, not just that they
        # were absent to begin with.
        conf_path = os.path.join(self.tmpdir.name, "automx.conf")
        lookup_path = os.path.join(self.tmpdir.name, "ldap-lookup.json")
        with open(conf_path, "w") as f:
            f.write("stale")
        with open(lookup_path, "w") as f:
            f.write("stale")

        agent = stub_agent.build(list_service_providers_result=[])
        with mock.patch.object(render, "agent", agent), \
                mock.patch.object(render.mail, "agent", agent):
            self.run_main_expecting_exit(render.EXIT_NOTHING_TO_RENDER)

        self.assertFalse(os.path.exists(conf_path))
        self.assertFalse(os.path.exists(lookup_path))

    def test_zero_enabled_domains_exits_nonzero(self):
        render.state.save_domains({"example.com": {"enabled": False}})
        agent = stub_agent.build(
            list_service_providers_result=[{"module_id": "mail1"}],
            tasks_run=lambda agent_id, action, data, **kw: {
                "get-configuration": {
                    "exit_code": 0,
                    "output": {"hostname": "mail.example.com", "user_domain": {"name": "ad.example.com"}},
                },
                "list-domains": {"exit_code": 0, "output": [{"domain": "example.com"}]},
            }[action],
        )
        with mock.patch.object(render, "agent", agent), \
                mock.patch.object(render.mail, "agent", agent):
            self.run_main_expecting_exit(render.EXIT_NOTHING_TO_RENDER)

    def _agent_for_successful_render(self, **kwargs):
        return stub_agent.build(
            list_service_providers_result=[{"module_id": "mail1"}],
            tasks_run=lambda agent_id, action, data, **kw: {
                "get-configuration": {
                    "exit_code": 0,
                    "output": {"hostname": "mail.example.com", "user_domain": {"name": "ad.example.com"}},
                },
                "list-domains": {"exit_code": 0, "output": [{"domain": "example.com"}]},
                "get-fqdn": {"exit_code": 0, "output": {"hostname": "node", "domain": "example.net"}},
            }[action],
            resolve_agent_id_result="node/1",
            ldap_domain={
                "host": "127.0.0.1", "port": 3890, "bind_dn": "x",
                "bind_password": "x", "base_dn": "x", "schema": "ad",
            },
            **kwargs,
        )

    def test_bind_user_domains_skipped_when_already_bound(self):
        # Real-node finding, 2026-09-22: bind_user_domains() unconditionally
        # re-fires module-domain-changed, and render-automx-conf runs on
        # every service start/reconcile -- calling it every time created a
        # self-sustaining event loop (our own module-domain-changed handler
        # calls reconcile(), which renders again, which re-binds again).
        # get_bound_domain_list() must be consulted first and the call
        # skipped when the binding hasn't actually changed.
        render.state.save_domains({"example.com": {"enabled": True}})
        agent = self._agent_for_successful_render(bound_domain_list=["ad.example.com"])
        with mock.patch.object(render, "agent", agent), \
                mock.patch.object(render.mail, "agent", agent), \
                mock.patch.object(render.automx_node, "agent", agent):
            render.main()

        agent.bind_user_domains.assert_not_called()

    def test_bind_user_domains_called_when_not_yet_bound(self):
        render.state.save_domains({"example.com": {"enabled": True}})
        agent = self._agent_for_successful_render(bound_domain_list=[])
        with mock.patch.object(render, "agent", agent), \
                mock.patch.object(render.mail, "agent", agent), \
                mock.patch.object(render.automx_node, "agent", agent):
            render.main()

        agent.bind_user_domains.assert_called_once_with(["ad.example.com"])

    def test_bind_user_domains_called_when_binding_differs(self):
        render.state.save_domains({"example.com": {"enabled": True}})
        agent = self._agent_for_successful_render(bound_domain_list=["some-other.example.com"])
        with mock.patch.object(render, "agent", agent), \
                mock.patch.object(render.mail, "agent", agent), \
                mock.patch.object(render.automx_node, "agent", agent):
            render.main()

        agent.bind_user_domains.assert_called_once_with(["ad.example.com"])


if __name__ == "__main__":
    unittest.main()

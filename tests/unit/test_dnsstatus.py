#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit test for automx.dnsstatus's resolver-check subprocess invocation
# (DESIGN.md 5.4). Added after two real-node findings (2026-09-22), both
# masked by the same "unknown status" fallback until tested on a real node:
# the original command list, ["podman", "run", "--rm", image,
# "automx-dns-check"], runs "automx automx-dns-check" because the image's
# own ENTRYPOINT is ["tini", "--", "automx"] and plain `podman run <image>
# <args>` appends rather than replaces it (the same bug class already
# caught in reload-automx's run_validate()); and even after adding
# --entrypoint, `input=` was never delivered to the script because plain
# `podman run` doesn't attach the container's stdin without --interactive.
# This call site had no test at all before.

import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "imageroot", "pypkg"))
sys.path.insert(0, HERE)
import stub_agent  # noqa: E402

# dnsstatus imports dnshelperclient, which imports "agent" at module level.
# Without the stub this file only passed when another test had loaded it.
_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent, "agent.ldapproxy": _agent.ldapproxy}):
    from automx import dnsstatus  # noqa: E402


class ResolverCheckSubprocessTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = mock.patch.dict(os.environ, {"AUTOMX_APP_IMAGE": "test-image:tag"})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_invokes_script_via_entrypoint_override_not_as_automx_subcommand(self):
        expected = [{"host": "autoconfig.example.com", "type": "CNAME", "value": "node.example.net"}]
        completed = mock.Mock(returncode=0, stdout=json.dumps([]))
        with mock.patch.object(dnsstatus.subprocess, "run", return_value=completed) as run_mock:
            dnsstatus._resolver_check(expected)

        args = run_mock.call_args[0][0]
        # The whole point: "automx-dns-check" must be the --entrypoint
        # value, never a bare trailing argv token (which the image's
        # tini/automx entrypoint would swallow as an invalid automx
        # subcommand instead of running the script).
        self.assertIn("--entrypoint", args)
        entrypoint_index = args.index("--entrypoint")
        self.assertEqual(args[entrypoint_index + 1], "automx-dns-check")
        self.assertNotIn("automx-dns-check", args[entrypoint_index + 2:])
        self.assertEqual(args[-1], "test-image:tag")
        # --interactive is required for subprocess.run's input= to actually
        # reach the container's stdin.
        self.assertIn("--interactive", args)
        self.assertEqual(run_mock.call_args.kwargs.get("input"), json.dumps(expected))

    def test_nonzero_exit_falls_back_to_unknown_status(self):
        expected = [{"host": "autoconfig.example.com", "type": "CNAME", "value": "node.example.net"}]
        completed = mock.Mock(returncode=1, stdout="", stderr="boom")
        with mock.patch.object(dnsstatus.subprocess, "run", return_value=completed):
            result = dnsstatus._resolver_check(expected)

        self.assertEqual(result[0]["status"], dnsstatus.dns.STATUS_UNKNOWN)

    def test_success_parses_script_output(self):
        expected = [{"host": "autoconfig.example.com", "type": "CNAME", "value": "node.example.net"}]
        script_output = [{"host": "autoconfig.example.com", "type": "CNAME", "value": "node.example.net", "status": "ok"}]
        completed = mock.Mock(returncode=0, stdout=json.dumps(script_output))
        with mock.patch.object(dnsstatus.subprocess, "run", return_value=completed):
            result = dnsstatus._resolver_check(expected)

        self.assertEqual(result, script_output)


class PerRecordAccessTests(unittest.TestCase):
    """A rule that names the zone but not every record (a user's node,
    2026-10-30: CNAME in all zones, SRV only in another zone). dnshelper's
    get-records hides the SRV, which must not be reported as missing."""

    DOMAIN = "example.com"
    TARGET = "node.example.net"
    CNAMES = [
        {"name": "autoconfig", "type": "CNAME", "ttl": 0, "data": "node.example.net."},
        {"name": "autodiscover", "type": "CNAME", "ttl": 0, "data": "node.example.net."},
    ]

    def status(self, zone_info, zone_records):
        client = dnsstatus.dnshelperclient
        with mock.patch.object(client, "has_zone", return_value=zone_info) as has_zone, mock.patch.object(
            client, "get_records", return_value=zone_records
        ):
            out = dnsstatus.domain_dns_status(self.DOMAIN, self.TARGET, "module/dnshelper1")
        self.assertEqual(
            has_zone.call_args[0][2],
            [
                {"name": "autoconfig.example.com", "type": "CNAME"},
                {"name": "autodiscover.example.com", "type": "CNAME"},
                {"name": "_autodiscover._tcp.example.com", "type": "SRV"},
            ],
        )
        return {r["type"] + " " + r["host"]: r["status"] for r in out["records"]}

    def access(self, srv_read, srv_write):
        return [
            {"name": "autoconfig.example.com", "type": "CNAME", "read": True, "write": True},
            {"name": "autodiscover.example.com", "type": "CNAME", "read": True, "write": True},
            {"name": "_autodiscover._tcp.example.com", "type": "SRV", "read": srv_read, "write": srv_write},
        ]

    def test_hidden_record_is_not_permitted_not_missing(self):
        info = {"managed": True, "zone": "example.com", "allowed": True, "records": self.access(False, False)}
        statuses = self.status(info, self.CNAMES)
        self.assertEqual(statuses["SRV _autodiscover._tcp.example.com"], dnsstatus.dns.STATUS_NOT_PERMITTED)
        self.assertEqual(statuses["CNAME autoconfig.example.com"], dnsstatus.dns.STATUS_OK)

    def test_readable_but_not_writable(self):
        info = {"managed": True, "zone": "example.com", "allowed": True, "records": self.access(True, False)}
        srv = {"name": "_autodiscover._tcp", "type": "SRV", "ttl": 0, "data": "0 0 443 node.example.net."}
        # Present and right: nothing to change, so it is simply ok.
        self.assertEqual(self.status(info, self.CNAMES + [srv])["SRV _autodiscover._tcp.example.com"], "ok")
        # Missing: it can't be created without a rule.
        self.assertEqual(
            self.status(info, self.CNAMES)["SRV _autodiscover._tcp.example.com"], dnsstatus.dns.STATUS_NOT_PERMITTED
        )

    def test_older_dnshelper_without_per_record_answer_keeps_old_behavior(self):
        info = {"managed": True, "zone": "example.com", "allowed": True}
        self.assertEqual(
            self.status(info, self.CNAMES)["SRV _autodiscover._tcp.example.com"], dnsstatus.dns.STATUS_MISSING
        )


if __name__ == "__main__":
    unittest.main()

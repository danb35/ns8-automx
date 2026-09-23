#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit tests for automx.dnshelperclient's error parsing. Added after a
# real-node finding (2026-09-22): on a validation-failed dnshelper task,
# the structured [{"field", "error", "message"}] list dnshelper's own
# contract documents comes back as response["output"], not
# response["error"] as the code originally assumed -- response["error"] is
# actually dnshelper's raw, unstructured audit log line. Confirmed by
# reading the raw task record straight from Redis for a real
# append-records conflict. Every error path exercised before this (e.g.
# has-zone's managed/allowed flags) went through a *successful* call, so
# the wrong field never got hit until a real conflict did.

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "imageroot", "pypkg"))
sys.path.insert(0, HERE)
import stub_agent  # noqa: E402

_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent, "agent.ldapproxy": _agent.ldapproxy}):
    from automx import dnshelperclient  # noqa: E402


def patched_client(tasks_run):
    """Context manager: dnshelperclient with its already-bound `agent`
    swapped for a stub whose tasks.run() is `tasks_run`, following the
    pattern test_render_automx_conf.py uses for render-automx-conf."""
    agent = stub_agent.build(tasks_run=tasks_run)
    return mock.patch.object(dnshelperclient, "agent", agent)


class CallErrorParsingTests(unittest.TestCase):
    def test_structured_error_comes_from_output_not_error_field(self):
        # This is the exact shape a real conflict produced on a live node:
        # response["output"] holds dnshelper's documented structured error,
        # response["error"] holds its raw audit log line.
        def tasks_run(agent_id, action, data, **kw):
            return {
                "exit_code": 2,
                "output": [
                    {
                        "field": "records",
                        "parameter": "records",
                        "value": "",
                        "error": "conflict",
                        "message": "autoconfig has a CNAME, which cannot coexist with A records",
                    }
                ],
                "error": '<6>dnshelper audit: caller="module/automx1" action="append-records" '
                'result="rejected" error="conflict" zone="example.com"',
            }

        with patched_client(tasks_run), self.assertRaises(dnshelperclient.DnshelperError) as cm:
            dnshelperclient.append_records("dnshelper1", "example.com", [])

        self.assertEqual(cm.exception.code, "conflict")
        self.assertIn("cannot coexist", cm.exception.message)

    def test_no_structured_output_falls_back_to_error_field(self):
        # DESIGN.md 3.5: "Provider timeouts fail the step" -- no structured
        # output to parse in that case, so the raw error field is all
        # there is for a message.
        def tasks_run(agent_id, action, data, **kw):
            return {"exit_code": 1, "output": None, "error": "provider timeout after 30s"}

        with patched_client(tasks_run), self.assertRaises(dnshelperclient.DnshelperError) as cm:
            dnshelperclient.get_records("dnshelper1", "example.com")

        self.assertEqual(cm.exception.code, "unknown")
        self.assertIn("timeout", cm.exception.message)

    def test_success_returns_output_directly(self):
        def tasks_run(agent_id, action, data, **kw):
            return {"exit_code": 0, "output": {"records": []}, "error": None}

        with patched_client(tasks_run):
            self.assertEqual(dnshelperclient.get_records("dnshelper1", "example.com"), [])


if __name__ == "__main__":
    unittest.main()

#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit test for imageroot/events/module-domain-changed/10reconcile. Added
# after a real-node finding (2026-09-22): this handler originally called
# reconcile() unconditionally for every module-domain-changed event, with
# a comment claiming that was fine since reconcile() is "cheap enough...
# and idempotent either way." In fact the event is published cluster-wide
# whenever *any* module calls agent.bind_user_domains() (confirmed by
# reading the actual publisher, ns8-core's
# cluster/actions/bind-user-domains/50bind_user_domains, which sends
# {"modules": [<the calling module's id>], "domains": [...]} on the shared
# cluster/event/module-domain-changed channel with no scoping), and a full
# reconcile costs real work -- without a filter, reacting to some other
# module's own routine rebinding created a permanent, self-sustaining
# reconcile loop (confirmed live via journalctl: "Handler of
# cluster/event/module-domain-changed is starting" firing indefinitely,
# restarting automx.service every ~45-50s). The fix filters to our own
# MODULE_ID, the one piece of information this event actually gives to
# filter on.

import importlib.machinery
import importlib.util
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
with mock.patch.dict(sys.modules, {"agent": _agent, "agent.ldapproxy": _agent.ldapproxy}):
    from automx import mail, reconcile  # noqa: E402
# Without this, "automx.mail"/"automx.reconcile" are never actually cached
# in sys.modules under those names (observed directly: sys.modules.get
# ("automx.reconcile") is None right after the import above) -- so the
# handler script's own "from automx import mail, reconcile" below would
# re-execute both files from scratch, importing a *second*, distinct
# module object that this file's own mock.patch.object() calls (below)
# have no effect on. Registering them explicitly makes the cache behave
# normally, so the handler reuses these same, patchable instances.
sys.modules["automx.mail"] = mail
sys.modules["automx.reconcile"] = reconcile

HANDLER_PATH = os.path.join(REPO_ROOT, "imageroot", "events", "module-domain-changed", "10reconcile")


def run_handler(event, agent, module_id="automx1"):
    """Runs the handler script's module-level code with stdin=event (JSON)
    and MODULE_ID=module_id, agent/mail/reconcile all using the given stub.
    Returns the (patched) reconcile module so call assertions can be made
    against reconcile.reconcile."""
    with mock.patch.dict(os.environ, {"MODULE_ID": module_id, "AGENT_INSTALL_DIR": os.path.join(REPO_ROOT, "imageroot")}), \
            mock.patch.object(mail, "agent", agent), \
            mock.patch.object(reconcile, "reconcile", return_value={}) as reconcile_mock, \
            mock.patch("json.load", return_value=event):
        loader = importlib.machinery.SourceFileLoader("module_domain_changed_10reconcile", HANDLER_PATH)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"agent": agent, "agent.ldapproxy": agent.ldapproxy}):
            try:
                loader.exec_module(module)
            except SystemExit:
                pass
    return reconcile_mock


class ModuleDomainChangedFilterTests(unittest.TestCase):
    def test_reconciles_when_our_own_module_changed(self):
        agent = stub_agent.build(
            tasks_run=lambda agent_id, action, data, **kw: {
                "get-configuration": {
                    "exit_code": 0,
                    "output": {"hostname": "mail.example.com", "user_domain": {"name": "example.com"}},
                },
                "list-domains": {"exit_code": 0, "output": [{"domain": "example.com"}]},
            }[action],
            list_service_providers_result=[{"module_id": "mail1"}],
        )
        reconcile_mock = run_handler({"modules": ["automx1"], "domains": ["example.com"]}, agent, module_id="automx1")
        reconcile_mock.assert_called_once()

    def test_skips_when_a_different_module_changed(self):
        agent = stub_agent.build()
        reconcile_mock = run_handler({"modules": ["ldapproxy1"], "domains": ["example.com"]}, agent, module_id="automx1")
        reconcile_mock.assert_not_called()

    def test_skips_when_modules_key_is_missing(self):
        agent = stub_agent.build()
        reconcile_mock = run_handler({"domains": ["example.com"]}, agent, module_id="automx1")
        reconcile_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

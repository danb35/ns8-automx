#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# automx.mail's binding to a mail module by UUID (DESIGN.md decision #15):
# a stored binding wins over node proximity, is never silently replaced,
# and a missing bound module means "not found", not "use another one".

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "imageroot", "pypkg"))
sys.path.insert(0, HERE)
import stub_agent  # noqa: E402

_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent}):
    sys.modules.pop("automx.mail", None)
    from automx import mail  # noqa: E402

NEAR = {"module_id": "mail2", "module_uuid": "uuid-near", "user_domain": "near.example", "node": "2"}
FAR = {
    "module_id": "mail1",
    "module_uuid": "uuid-far",
    "user_domain": "far.example",
    "node": "1",
    "ui_name": "Main",
    "mail_hostname": "mail.far.example",
}


def list_service_providers(rdb, service, transport="*", filters={}):
    providers = [NEAR, FAR]
    if "module_uuid" in filters:
        return [p for p in providers if p["module_uuid"] == filters["module_uuid"]]
    return list(providers)


class FakeRedis:
    def __init__(self, envs):
        self.envs = envs

    def hkeys(self, key):
        return list(self.envs)

    def hgetall(self, key):
        return dict(self.envs.get(key.split("/")[1], {}))


class MailTestCase(unittest.TestCase):
    def setUp(self):
        self.agent = stub_agent.build()
        self.agent.list_service_providers = mock.Mock(side_effect=list_service_providers)
        for patcher in (
            mock.patch.object(mail, "agent", self.agent),
            mock.patch.dict(os.environ, {"MODULE_ID": "automx1"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("MAIL_SERVER", None)
        self.rdb = FakeRedis({})


class BindingTests(MailTestCase):
    def test_without_a_binding_the_nearest_is_used(self):
        self.assertEqual(mail.find_instance(self.rdb), "mail2")
        self.assertEqual(mail.current_uuid(self.rdb), "uuid-near")

    def test_a_binding_wins_over_proximity(self):
        os.environ["MAIL_SERVER"] = "uuid-far"
        self.assertEqual(mail.find_instance(self.rdb), "mail1")

    def test_an_explicit_uuid_wins_over_the_binding(self):
        os.environ["MAIL_SERVER"] = "uuid-far"
        self.assertEqual(mail.find_instance(self.rdb, "uuid-near"), "mail2")

    def test_a_bound_module_that_is_gone_is_not_replaced(self):
        os.environ["MAIL_SERVER"] = "uuid-gone"
        self.assertIsNone(mail.find_instance(self.rdb))
        self.assertEqual(mail.current_uuid(self.rdb), "uuid-gone")
        with self.assertRaises(mail.MailNotFound):
            mail.get_instance_info(self.rdb)
        mail.ensure_bound(self.rdb)
        self.agent.set_env.assert_not_called()

    def test_bind_reaches_this_process_too(self):
        mail.bind("uuid-far")
        self.agent.set_env.assert_called_once_with("MAIL_SERVER", "uuid-far")
        self.assertEqual(mail.bound_uuid(), "uuid-far")

    def test_ensure_bound_records_the_module_in_use(self):
        mail.ensure_bound(self.rdb)
        self.agent.set_env.assert_called_once_with("MAIL_SERVER", "uuid-near")

    def test_ensure_bound_keeps_a_stored_binding(self):
        os.environ["MAIL_SERVER"] = "uuid-far"
        mail.ensure_bound(self.rdb)
        self.agent.set_env.assert_not_called()

    def test_ensure_bound_without_any_mail_module(self):
        self.agent.list_service_providers = mock.Mock(return_value=[])
        mail.ensure_bound(self.rdb)
        self.agent.set_env.assert_not_called()


class UsersTests(MailTestCase):
    def test_users_of_finds_other_automx_instances_only(self):
        rdb = FakeRedis(
            {
                "automx1": {"IMAGE_URL": "ghcr.io/danb35/automx:0.2.6", "MAIL_SERVER": "uuid-own"},
                "automx2": {"IMAGE_URL": "ghcr.io/danb35/automx:0.2.6", "MAIL_SERVER": "uuid-far"},
                "automx3": {"IMAGE_URL": "ghcr.io/danb35/automx:0.2.6"},
                "piler1": {"IMAGE_URL": "ghcr.io/nethserver/piler:1.0.0", "MAIL_SERVER": "uuid-near"},
                "broken1": {},
            }
        )
        self.assertEqual(mail.users_of(rdb), {"uuid-far": "automx2"})

    def test_list_servers(self):
        rdb = FakeRedis({"automx2": {"IMAGE_URL": "ghcr.io/danb35/automx:0.2.6", "MAIL_SERVER": "uuid-far"}})
        self.assertEqual(
            mail.list_servers(rdb),
            [
                {
                    "module_uuid": "uuid-near",
                    "module_id": "mail2",
                    "ui_name": "",
                    "hostname": "",
                    "user_domain": "near.example",
                    "node": "2",
                    "used_by": None,
                },
                {
                    "module_uuid": "uuid-far",
                    "module_id": "mail1",
                    "ui_name": "Main",
                    "hostname": "mail.far.example",
                    "user_domain": "far.example",
                    "node": "1",
                    "used_by": "automx2",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()

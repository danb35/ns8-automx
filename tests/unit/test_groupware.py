#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit tests for automx.groupware (DESIGN.md 2, v2 scope): which installed
# Nextcloud/SOGo/WebTop modules can provide CalDAV/CardDAV and ActiveSync
# for the mail instance, read from a fake Redis shaped like ns8-core's
# (cluster/module_node, cluster/module_domains, module/<id>/environment).

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
    from automx import groupware  # noqa: E402

MAIL_UUID = "11111111-2222-3333-4444-555555555555"
USER_DOMAIN = "ad.example.com"


class FakeRedis:
    def __init__(self, hashes):
        self.hashes = hashes

    def hkeys(self, key):
        return list(self.hashes.get(key, {}))

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))


def module(image, node="1", **env):
    return {"IMAGE_URL": f"ghcr.io/nethserver/{image}:1.0.0", "NODE_ID": node, **env}


class ListCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.modules = {"mail1": module("mail", MODULE_UUID=MAIL_UUID)}
        self.bound = {}
        self.routes = {}
        patches = [
            mock.patch.object(groupware.agent, "get_bound_domain_list", side_effect=self._bound),
            mock.patch.object(groupware.agent, "get_route", side_effect=lambda mid: self.routes.get(mid, {})),
            mock.patch.dict(os.environ, {"NODE_ID": "1"}),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _bound(self, rdb, module_id):
        return self.bound.get(module_id, [])

    def add(self, module_id, env, domains=(USER_DOMAIN,)):
        self.modules[module_id] = env
        self.bound[module_id] = list(domains)

    def candidates(self):
        hashes = {"cluster/module_node": {mid: env["NODE_ID"] for mid, env in self.modules.items()}}
        for mid, env in self.modules.items():
            hashes[f"module/{mid}/environment"] = env
        return groupware.list_candidates(FakeRedis(hashes), "mail1", USER_DOMAIN)

    def test_sogo_with_dav_and_activesync(self):
        self.add("sogo1", module("sogo", TRAEFIK_HOST="sogo.example.com", DAV="True", ACTIVESYNC="True", MAIL_SERVER=MAIL_UUID))
        self.assertEqual(
            self.candidates(),
            [
                {
                    "module_id": "sogo1",
                    "kind": "sogo",
                    "host": "sogo.example.com",
                    "dav_url": "https://sogo.example.com/SOGo/dav/",
                    "activesync_url": "https://sogo.example.com/Microsoft-Server-ActiveSync",
                }
            ],
        )

    def test_sogo_flags_off(self):
        self.add("sogo1", module("sogo", TRAEFIK_HOST="sogo.example.com", DAV="False", ACTIVESYNC="True", MAIL_SERVER=MAIL_UUID))
        (candidate,) = self.candidates()
        self.assertIsNone(candidate["dav_url"])
        self.assertIsNotNone(candidate["activesync_url"])

    def test_sogo_with_both_off_is_left_out(self):
        self.add("sogo1", module("sogo", TRAEFIK_HOST="sogo.example.com", DAV="False", ACTIVESYNC="False", MAIL_SERVER=MAIL_UUID))
        self.assertEqual(self.candidates(), [])

    def test_activesync_needs_the_same_mail_module(self):
        # ActiveSync carries the mail too, so it must be the same mail
        # server; DAV only needs the same user domain.
        self.add("webtop1", module("webtop", WEBTOP_HOSTNAME="webtop.example.com", MAIL_MODULE_UUID="other-uuid"))
        (candidate,) = self.candidates()
        self.assertEqual(candidate["dav_url"], "https://webtop.example.com/webtop-dav/server.php")
        self.assertIsNone(candidate["activesync_url"])

    def test_webtop_with_same_mail_module(self):
        self.add("webtop1", module("webtop", WEBTOP_HOSTNAME="webtop.example.com", MAIL_MODULE_UUID=MAIL_UUID))
        (candidate,) = self.candidates()
        self.assertEqual(candidate["activesync_url"], "https://webtop.example.com/Microsoft-Server-ActiveSync")

    def test_other_user_domain_is_left_out(self):
        self.add("sogo1", module("sogo", TRAEFIK_HOST="sogo.example.com", MAIL_SERVER=MAIL_UUID), domains=["other.example.com"])
        self.assertEqual(self.candidates(), [])

    def test_nextcloud_host_comes_from_its_route_on_this_node(self):
        self.add("nextcloud1", module("nextcloud"))
        self.routes["nextcloud1"] = {"instance": "nextcloud1", "host": "cloud.example.com"}
        self.assertEqual(
            self.candidates(),
            [
                {
                    "module_id": "nextcloud1",
                    "kind": "nextcloud",
                    "host": "cloud.example.com",
                    "dav_url": "https://cloud.example.com/remote.php/dav/",
                    "activesync_url": None,
                }
            ],
        )

    def test_nextcloud_on_another_node_is_left_out(self):
        # Its host is only in its Traefik route, and this module can only
        # read routes on its own node.
        self.add("nextcloud1", module("nextcloud", node="2"))
        self.routes["nextcloud1"] = {"host": "cloud.example.com"}
        self.assertEqual(self.candidates(), [])
        groupware.agent.get_route.assert_not_called()

    def test_module_without_a_host_yet_is_left_out(self):
        self.add("sogo1", module("sogo", MAIL_SERVER=MAIL_UUID))
        self.add("nextcloud1", module("nextcloud"))
        self.assertEqual(self.candidates(), [])

    def test_unrelated_modules_are_ignored(self):
        self.add("dokuwiki1", module("dokuwiki", TRAEFIK_HOST="wiki.example.com"))
        self.assertEqual(self.candidates(), [])

    def test_find(self):
        candidates = [{"module_id": "sogo1", "dav_url": "https://x/SOGo/dav/", "activesync_url": None}]
        self.assertEqual(groupware.find(candidates, "sogo1", "dav_url"), "https://x/SOGo/dav/")
        self.assertIsNone(groupware.find(candidates, "sogo1", "activesync_url"))
        self.assertIsNone(groupware.find(candidates, "sogo2", "dav_url"))


if __name__ == "__main__":
    unittest.main()

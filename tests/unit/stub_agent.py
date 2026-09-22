#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# A fake "agent" module (the NS8 agent SDK, only ever importable on a real
# node) for unit-testing code under imageroot/ without one. Modeled on
# ns8-dnshelper's own tests/unit test pattern: build a types.ModuleType and
# inject it into sys.modules before importing the code under test, rather
# than mocking each call site individually.
#
# Usage:
#   import sys
#   from unittest import mock
#   import stub_agent
#
#   agent = stub_agent.build(tasks_run=lambda agent_id, action, data: {...})
#   with mock.patch.dict(sys.modules, {"agent": agent, "agent.ldapproxy": agent.ldapproxy}):
#       import render_automx_conf  # or whatever imports "agent"

import types
from unittest import mock


class LdapproxyStub:
    """Stand-in for agent.ldapproxy.Ldapproxy. get_domain_result and
    filter_clause are set once on the class/instance by the test; every
    Ldapproxy() call (the real code does `Ldapproxy()` fresh each time)
    returns an object backed by the same values."""

    get_domain_result = None
    filter_clause = ""
    calls = []

    def get_domain(self, name):
        type(self).calls.append(("get_domain", name))
        return type(self).get_domain_result

    def get_ldap_users_search_filter_clause(self):
        type(self).calls.append(("get_ldap_users_search_filter_clause",))
        return type(self).filter_clause


def build(
    *,
    tasks_run=None,
    redis=None,
    list_service_providers_result=None,
    resolve_agent_id_result=None,
    get_route_result=None,
    ldap_domain=None,
    hidden_users_filter="",
):
    """A fresh fake agent module. Pass tasks_run(agent_id, action, data) to
    control agent.tasks.run()'s response; everything else has a reasonable
    default a test can override piecemeal via the returned module's
    attributes (they're plain mocks/values, not locked down)."""
    agent = types.ModuleType("agent")
    agent.SD_ERR = "<3>"
    agent.SD_WARNING = "<4>"
    agent.SD_NOTICE = "<5>"
    agent.SD_INFO = "<6>"

    agent.status_calls = []
    agent.set_status = lambda status: agent.status_calls.append(status)

    def assert_exp(condition, message="assertion failed"):
        if not condition:
            raise AssertionError(message)

    agent.assert_exp = assert_exp

    agent.redis_connect = mock.Mock(return_value=redis if redis is not None else mock.Mock())

    agent.list_service_providers = mock.Mock(
        return_value=list_service_providers_result if list_service_providers_result is not None else []
    )

    agent.resolve_agent_id = mock.Mock(return_value=resolve_agent_id_result)

    agent.route_calls = []

    def set_route(data, error_passthrough=True, agent_id=None):
        agent.route_calls.append(("set_route", data))
        return {"exit_code": 0, "output": dict(data), "error": None}

    agent.set_route = mock.Mock(side_effect=set_route)
    agent.get_route = mock.Mock(return_value=get_route_result if get_route_result is not None else {})

    agent.bind_user_domains = mock.Mock()

    helper_result = mock.Mock()
    helper_result.check_returncode = mock.Mock()
    agent.run_helper = mock.Mock(return_value=helper_result)

    agent.set_env = mock.Mock()

    def default_tasks_run(agent_id=None, action=None, data=None, **kwargs):
        raise AssertionError(f"unexpected agent.tasks.run({agent_id!r}, action={action!r})")

    agent.tasks = types.SimpleNamespace(run=mock.Mock(side_effect=tasks_run or default_tasks_run))

    LdapproxyStub.get_domain_result = ldap_domain
    LdapproxyStub.filter_clause = hidden_users_filter
    LdapproxyStub.calls = []

    ldapproxy_module = types.ModuleType("agent.ldapproxy")
    ldapproxy_module.Ldapproxy = LdapproxyStub
    agent.ldapproxy = ldapproxy_module

    return agent

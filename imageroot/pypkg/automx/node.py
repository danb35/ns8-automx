#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# node/get-fqdn (DESIGN.md 4.5's node:reader authorization exists for this
# call): returns {"hostname", "domain"}, joined here into the FQDN used as
# the default CNAME/SRV target and service host (5.1, 7.1) when no
# service_host override is set.
#
# Real-node finding (2026-09-22): agent.tasks.run() does not resolve a bare
# "node" selector itself (unlike the CLI/`resolve_agent_id`'s own special
# case for it) -- passing it straight through produces a malformed task URL
# (.../api/node/tasks, missing the node id) and a 404. Resolve it first,
# the same way dnshelperclient.py resolves "dnshelper@cluster" before
# calling tasks.run with the result.

import agent


def get_node_fqdn():
    node_agent_id = agent.resolve_agent_id("node")
    response = agent.tasks.run(node_agent_id, action="get-fqdn", data={})
    agent.assert_exp(response["exit_code"] == 0, "node/get-fqdn failed")
    out = response["output"]
    return f"{out['hostname']}.{out['domain']}"

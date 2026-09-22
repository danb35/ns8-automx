#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# node/get-fqdn (DESIGN.md 4.5's node:reader authorization exists for this
# call): returns {"hostname", "domain"}, joined here into the FQDN used as
# the default CNAME/SRV target and service host (5.1, 7.1) when no
# service_host override is set.

import agent


def get_node_fqdn():
    response = agent.tasks.run("node", action="get-fqdn", data={})
    agent.assert_exp(response["exit_code"] == 0, "node/get-fqdn failed")
    out = response["output"]
    return f"{out['hostname']}.{out['domain']}"

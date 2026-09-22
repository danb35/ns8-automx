#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Thin wrapper around the dnshelper consumer contract (CLAUDE.md: read from
# ns8-dnshelper's own README/schemas, not from memory -- done for this file
# against /Users/dan/Documents/GitHub/ns8-dnshelper, 2026-09-22).
#
# Key facts this wrapper relies on:
# - Find the cluster's default instance with agent.resolve_agent_id
#   ("dnshelper@cluster") (matches our own "dnshelper@cluster:dnswriter"
#   authorization grant) -- not list_service_providers, which would pick an
#   arbitrary instance if the cluster ever has more than one.
# - Every write action (append/set/delete-records) accepts dry_run and
#   returns {"dry_run", "changes": {"add", "remove"}, "records"}.
# - A record is {"name", "type", "ttl", "data"}; name is relative to the
#   zone ("@" for the apex); data is unescaped zone-file RDATA (SRV:
#   "priority weight port target").
# - User-fixable errors come back as an NS8 validation failure: a
#   single-item list [{"field", "parameter", "value", "error", "message"}],
#   with "error" one of not_permitted/zone_not_found/conflict/forbidden/
#   auth_failed/unsupported/invalid_request/unknown_provider (dnshelper's
#   own dnshelper_lib.ActionError.entry). Provider outages/timeouts fail
#   the task step instead (no structured error to parse).
# - Every call reads the zone first; some providers take 8-15s. Callers
#   must batch by zone, never call per-record in a loop.

import agent


class DnshelperError(Exception):
    """A user-fixable dnshelper refusal (not_permitted, conflict, ...)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def find_instance():
    """The cluster's default dnshelper agent_id (e.g. "module/dnshelper1"),
    or None if dnshelper is not installed."""
    return agent.resolve_agent_id("dnshelper@cluster")


def _call(target, action, data):
    response = agent.tasks.run(agent_id=target, action=action, data=data)
    if response["exit_code"] == 0:
        return response["output"]

    # Real-node finding (2026-09-22): on a validation-failed exit, dnshelper's
    # own structured [{"field", "parameter", "value", "error", "message"}]
    # list (its documented contract) comes back as response["output"], not
    # response["error"] -- that field instead holds dnshelper's raw audit
    # log line (e.g. `<6>dnshelper audit: ... error="conflict" ...`), an
    # unstructured string. Every call site that had exercised an error path
    # before this (has-zone's managed/allowed flags) got there through a
    # *successful* (exit_code 0) call, so this was never hit until a real
    # append-records conflict did. Confirmed via the raw task record in
    # Redis (task/module/<dnshelper>/<task id>/{output,error,exit_code}).
    error = response.get("output")
    if isinstance(error, list) and error:
        error = error[0]
    if isinstance(error, dict):
        raise DnshelperError(error.get("error", "unknown"), error.get("message", ""))
    # No structured output (provider outage/timeout, DESIGN.md 3.5): fall
    # back to whatever response["error"] has, for a message at least.
    fallback = response.get("error")
    raise DnshelperError("unknown", str(fallback) if fallback else "dnshelper call failed")


def has_zone(target, name):
    """{"managed": bool, "zone": str|None, "allowed": bool}"""
    return _call(target, "has-zone", {"name": name})


def get_records(target, zone, name=None, type=None):
    data = {"zone": zone}
    if name is not None:
        data["name"] = name
    if type is not None:
        data["type"] = type
    return _call(target, "get-records", data)["records"]


def append_records(target, zone, records, dry_run=False):
    return _call(target, "append-records", {"zone": zone, "records": records, "dry_run": dry_run})


def set_records(target, zone, records, dry_run=False, mode="merge", replace_prefixes=None):
    data = {"zone": zone, "records": records, "dry_run": dry_run, "mode": mode}
    if replace_prefixes is not None:
        data["replace_prefixes"] = replace_prefixes
    return _call(target, "set-records", data)


def delete_records(target, zone, records, dry_run=False):
    return _call(target, "delete-records", {"zone": zone, "records": records, "dry_run": dry_run})

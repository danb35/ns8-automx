#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Computes the DNS status (DESIGN.md 5.2/5.3/5.4) for one domain's three
# expected records, either through dnshelper (if present and covering the
# zone) or through a resolver-based check (imageroot/bin/automx-dns-check,
# run in an ephemeral automx-app container -- see VERIFY item 7).

import json
import os
import subprocess

from automx import dns, dnshelperclient


def domain_dns_status(domain, target_fqdn, dnshelper_target):
    """Returns {"managed": bool, "zone": str|None, "allowed": bool|None,
    "records": [{"host", "type", "value", "status"}]}."""
    expected = dns.expected_records(domain, target_fqdn)

    if dnshelper_target is None:
        return {
            "managed": False,
            "zone": None,
            "allowed": None,
            "records": _resolver_check(expected),
        }

    zone_info = dnshelperclient.has_zone(dnshelper_target, domain)
    if not zone_info["managed"]:
        return {
            "managed": False,
            "zone": None,
            "allowed": None,
            "records": [{**r, "status": dns.STATUS_UNMANAGED} for r in _as_status_records(expected)],
        }

    if not zone_info["allowed"]:
        return {
            "managed": True,
            "zone": zone_info["zone"],
            "allowed": False,
            "records": [{**r, "status": dns.STATUS_NOT_PERMITTED} for r in _as_status_records(expected)],
        }

    zone = zone_info["zone"]

    # One get-records call for the whole zone, not one per name: dnshelper
    # re-reads the zone on every call (seconds on a fast provider, 8-15s on
    # Hetzner), so fetching all three names' records individually would
    # triple the wait for no benefit -- filter client-side instead.
    try:
        zone_records = dnshelperclient.get_records(dnshelper_target, zone)
    except dnshelperclient.DnshelperError as exc:
        return {
            "managed": True,
            "zone": zone,
            "allowed": True,
            "records": [
                {**r, "status": dns.STATUS_UNKNOWN, "detail": exc.message}
                for r in _as_status_records(expected)
            ],
        }

    records = []
    for record in expected:
        relative_name = dns.dnshelper_relative_name(record["host"], zone)
        existing_at_name = [r for r in zone_records if r["name"] == relative_name]
        status, conflicts = dns.compare_record(record, existing_at_name)
        entry = {**record, "status": status}
        if conflicts:
            entry["conflicts"] = conflicts
        records.append(entry)

    return {"managed": True, "zone": zone, "allowed": True, "records": records}


def _as_status_records(expected):
    return [dict(r) for r in expected]


def _resolver_check(expected):
    try:
        result = subprocess.run(
            [
                "podman",
                "run",
                "--rm",
                # --interactive: subprocess.run's `input=` writes to the
                # child's stdin pipe, but plain `podman run` (no -i) doesn't
                # attach the container's stdin to it at all -- without this,
                # automx-dns-check sees an empty stdin and fails to parse it
                # as JSON. Found on a real node, 2026-09-22, right after the
                # --entrypoint fix below: fixing one revealed the other, both
                # previously masked by the same "unknown status" fallback.
                "--interactive",
                # --entrypoint: the image's own ENTRYPOINT is ["tini", "--",
                # "automx"], and plain `podman run <image> <args>` appends
                # args to that rather than replacing it (same bug class
                # found in reload-automx's run_validate() -- see DESIGN.md
                # 9). Without this override the command actually run is
                # "automx automx-dns-check", an invalid automx subcommand,
                # which exits nonzero and makes every record status
                # "unknown" -- found on a real node, 2026-09-22.
                "--entrypoint",
                "automx-dns-check",
                os.environ["AUTOMX_APP_IMAGE"],
            ],
            input=json.dumps(expected),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return [{**r, "status": dns.STATUS_UNKNOWN} for r in _as_status_records(expected)]
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return [{**r, "status": dns.STATUS_UNKNOWN} for r in _as_status_records(expected)]

#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The DNS record set a domain needs (DESIGN.md 5.1) and the status model
# used to compare it against what's actually published (5.2).

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_CONFLICT = "conflict"
STATUS_UNMANAGED = "unmanaged"
STATUS_NOT_PERMITTED = "not_permitted"
STATUS_UNKNOWN = "unknown"


def expected_records(domain, target_fqdn):
    """The three records DESIGN.md 5.1 wants for one enabled domain, as
    absolute {"host", "type", "value"} dicts (not zone-relative -- that
    depends on which zone a specific provider manages, see
    dnshelper_relative_name below).

    The CNAME/SRV target itself is given a trailing dot. Found on a real
    node, 2026-09-22: dnshelper does not append one on our behalf (it
    hands the RDATA to the provider largely as given -- see its
    records.go toLibdns()/libdns.RR.Parse()), and a target without one is
    standard-DNS *relative to the zone being written*, not absolute --
    writing target_fqdn bare through a real RFC 2136 (BIND) provider
    produced a CNAME literally pointing at
    "<target_fqdn>.<domain>." instead of "<target_fqdn>.", confirmed via
    dig against the zone afterward. automx-dns-check's own resolver-based
    comparison (5.4) already strips trailing dots on both sides before
    comparing, so it was never affected by this; only the create/
    overwrite path through dnshelper actually wrote wrong data."""
    target = target_fqdn.rstrip(".") + "."
    return [
        {"host": f"autoconfig.{domain}", "type": "CNAME", "value": target},
        {"host": f"autodiscover.{domain}", "type": "CNAME", "value": target},
        {
            "host": f"_autodiscover._tcp.{domain}",
            "type": "SRV",
            "value": f"0 0 443 {target}",
        },
    ]


def routes_ready(dns_status):
    """True if the two CNAME records Traefik's routes/certs actually depend
    on (autoconfig, autodiscover) are both published and correct. The SRV
    record is irrelevant here -- it's only for Outlook's own SRV discovery,
    which happens after a client already has a route/cert to talk to.

    This is the gate route creation waits on (DESIGN.md 5.6, 3.4): a route
    gets exactly one shot at a Let's Encrypt certificate (Traefik's ACME
    provider only (re-)tries a domain when its dynamic config changes --
    confirmed by reading traefik/traefik's pkg/provider/acme/provider.go,
    2026-09-23 -- there is no background poller retrying a domain that
    never got a cert). Creating the route before DNS resolves burns that
    one shot on a guaranteed failure and, worse, can exhaust Let's
    Encrypt's per-hostname failed-authorization rate limit, blocking any
    real retry for up to an hour even after DNS is fixed -- exactly what
    happened enabling a domain live, 2026-09-23."""
    return all(r["status"] == STATUS_OK for r in dns_status["records"] if r["type"] == "CNAME")


def dnshelper_relative_name(host, zone):
    """host relative to the dnshelper-managed zone, "@" at the apex.
    A mail domain can be a subdomain of the managed zone (DESIGN.md 5.3.1),
    so e.g. host="autoconfig.mail.example.com", zone="example.com" ->
    "autoconfig.mail"."""
    if host == zone:
        return "@"
    suffix = f".{zone}"
    if not host.endswith(suffix):
        raise ValueError(f"{host} is not inside zone {zone}")
    return host[: -len(suffix)]


def compare_record(expected, existing_records_at_name):
    """expected: one entry from expected_records(). existing_records_at_name:
    dnshelper get-records() output already filtered to that name (any type).
    Returns (status, conflicting_records) -- DESIGN.md 5.2/5.3.3: a CNAME
    conflicts with any other record at the same name; an SRV conflicts only
    with a different SRV RRset at that name."""
    if expected["type"] == "SRV":
        srv_records = [r for r in existing_records_at_name if r["type"] == "SRV"]
        if not srv_records:
            return STATUS_MISSING, []
        if any(r["data"] == expected["value"] for r in srv_records):
            return STATUS_OK, []
        return STATUS_CONFLICT, srv_records

    # CNAME: must be the only record at that name, with the right target.
    if not existing_records_at_name:
        return STATUS_MISSING, []
    if len(existing_records_at_name) == 1 and (
        existing_records_at_name[0]["type"] == "CNAME"
        and existing_records_at_name[0]["data"] == expected["value"]
    ):
        return STATUS_OK, []
    return STATUS_CONFLICT, existing_records_at_name

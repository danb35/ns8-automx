#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The create/overwrite record-change logic behind the apply-dns action
# (DESIGN.md 5.3.4): batches all three records into as few dnshelper calls
# as possible (dnshelper re-reads the zone on every call).

from automx import dns, dnshelperclient


def plan_changes(zone, expected_records, existing_records, action):
    """Splits expected_records into the dnshelper write calls needed to
    reach them, given existing_records (one get-records call's worth, for
    the whole zone) and action ("create" or "overwrite"). Returns
    {"delete": [...], "append": [...], "set": [...]} -- any of which may be
    empty. "create" only ever populates "append" (DESIGN.md 5.3.4: Create
    touches only missing records); "overwrite" may populate all three."""
    to_delete = []
    to_append = []
    to_set = []

    for record in expected_records:
        relative_name = dns.dnshelper_relative_name(record["host"], zone)
        existing_at_name = [r for r in existing_records if r["name"] == relative_name]
        status, conflicts = dns.compare_record(record, existing_at_name)

        if status == dns.STATUS_OK:
            continue

        if status == dns.STATUS_MISSING:
            to_append.append({"name": relative_name, "type": record["type"], "data": record["value"]})
            continue

        if status == dns.STATUS_CONFLICT and action == "overwrite":
            if record["type"] == "CNAME":
                other_type_conflicts = [c for c in conflicts if c["type"] != "CNAME"]
                if other_type_conflicts:
                    # dnshelper refuses a CNAME beside another record at the
                    # same name -- the conflicting type(s) must go first.
                    for conflict in other_type_conflicts:
                        to_delete.append({"name": relative_name, "type": conflict["type"]})
                    to_append.append(
                        {"name": relative_name, "type": "CNAME", "data": record["value"]}
                    )
                else:
                    # Same type, wrong value: rrset mode replaces it in place.
                    to_set.append({"name": relative_name, "type": "CNAME", "data": record["value"]})
            else:  # SRV: replace the whole SRV RRset at that name.
                to_set.append({"name": relative_name, "type": "SRV", "data": record["value"]})

    return {"delete": to_delete, "append": to_append, "set": to_set}


def apply_changes(target, zone, changes, dry_run):
    """Executes plan_changes()'s output in the required order (delete
    conflicting types before appending a CNAME over them) and returns
    {"delete": response|None, "append": response|None, "set": response|None}.
    Note: with dry_run=True, each call previews against the zone as it
    actually is right now, independently -- a delete's dry-run preview does
    not "apply" for the append dry-run call that follows, so a type-conflict
    preview may look more alarming than the real (sequential, non-dry-run)
    execution will be. This is a dnshelper limitation of previewing
    multi-step changes as separate calls, not a bug here."""
    responses = {"delete": None, "append": None, "set": None}
    if changes["delete"]:
        responses["delete"] = dnshelperclient.delete_records(
            target, zone, changes["delete"], dry_run=dry_run
        )
    if changes["append"]:
        responses["append"] = dnshelperclient.append_records(
            target, zone, changes["append"], dry_run=dry_run
        )
    if changes["set"]:
        responses["set"] = dnshelperclient.set_records(
            target, zone, changes["set"], dry_run=dry_run, mode="rrset"
        )
    return responses

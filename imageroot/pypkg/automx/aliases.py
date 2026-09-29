#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Alias resolution (DESIGN.md 2, v2 scope; 3.3 "phase 2"): a map from mail
# alias addresses to the login of the one user they deliver to, built from
# the mail module's list-addresses output and read by automx-ldap-lookup
# inside the container.
#
# list-addresses output, read from NethServer/ns8-mail (2026-09-29,
# pypkg/mail.py get_addresses()/DestEncoder): each address has "local",
# "atype" and, for the kinds that matter here, "destinations":
#   - atype "domain": bound to one "domain";
#   - atype "wildcard": the same local part on every mail domain;
#   - a user destination is {"dtype": "user", "name": <login>, ...} (the
#     "user" key in the schema's own examples is stale; the encoder writes
#     "name").
# atype "adduser"/"addgroup"/"addalias" are left out: adduser addresses
# are login@domain, which the LDAP lookup already resolves, addalias ones
# come from the users' LDAP mail attribute, which it also already matches,
# and a group has no single login.
#
# An alias is only mapped when it delivers to exactly one user. A shared
# address (several users, a group, a public folder, an external address)
# has no single login to hand out, so the client gets the usual fallback.

WILDCARD = "wildcard"
DOMAIN = "domain"


def _single_user(address):
    destinations = address.get("destinations") or []
    if len(destinations) != 1:
        return None
    destination = destinations[0]
    if destination.get("dtype") != "user":
        return None
    return destination.get("name") or None


def build_map(addresses, domains):
    """{"local@domain": "login"} for each address in list-addresses'
    "addresses" that delivers to exactly one user, limited to domains
    (the enabled mail domains). A domain-specific address wins over a
    wildcard one with the same local part, as it does in the mail
    server's own lookup order."""
    domains = {d.lower() for d in domains}
    wildcard = {}
    specific = {}
    for address in addresses:
        login = _single_user(address)
        local = (address.get("local") or "").lower()
        if not login or not local:
            continue
        if address.get("atype") == WILDCARD:
            wildcard[local] = login
        elif address.get("atype") == DOMAIN:
            domain = (address.get("domain") or "").lower()
            if domain in domains:
                specific[f"{local}@{domain}"] = login

    alias_map = {f"{local}@{domain}": login for local, login in wildcard.items() for domain in domains}
    alias_map.update(specific)
    return dict(sorted(alias_map.items()))

#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Pure merge of the mail module's current domain list with our own stored
# enable flags (DESIGN.md 4.2): a domain removed from mail is dropped from
# generated config/routes but its stored flag is kept and reported as
# "orphaned" until the administrator removes it. Factored out of
# get-domains/render-automx-conf/reconcile so the merge logic has exactly
# one implementation and is unit-testable without the NS8 agent framework.

def merge(mail_domain_names, domains_state):
    """All domains known either to mail or to our own state, each as
    {"domain", "enabled", "orphaned"}, sorted by domain name."""
    all_domains = sorted(set(mail_domain_names) | set(domains_state.keys()))
    return [
        {
            "domain": domain,
            "enabled": domains_state.get(domain, {}).get("enabled", False),
            "orphaned": domain not in mail_domain_names,
        }
        for domain in all_domains
    ]


def enabled_usable(mail_domain_names, domains_state):
    """Sorted domain names that are both enabled and still present in the
    mail module -- what the renderer and route reconciliation actually act
    on (DESIGN.md 4.2's "dropped from generated config" for a vanished
    domain, regardless of its stored flag)."""
    return sorted(
        domain
        for domain, flags in domains_state.items()
        if flags.get("enabled") and domain in mail_domain_names
    )

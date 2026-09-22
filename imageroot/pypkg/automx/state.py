#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Read/write helpers for the module's own state (DESIGN.md 4.2):
# state/domains.json ({"<domain>": {"enabled": bool}}) and state/settings.json.
# Both are backed up (imageroot/etc/state-include.conf); automx.conf and
# ldap-lookup.json, which are pure functions of these plus live discovery
# data, are not (see imageroot/bin/render-automx-conf).

import json
import os

STATE_DIR = os.environ.get("AGENT_STATE_DIR", "state")
DOMAINS_PATH = os.path.join(STATE_DIR, "domains.json")
SETTINGS_PATH = os.path.join(STATE_DIR, "settings.json")

# service_host: null means "use the node FQDN" (DESIGN.md 4.3/5.1).
# http2https: default true (DESIGN.md 4.4).
# display_names: default true, with the disclosure trade-off explained in
# the UI (DESIGN.md 8, decided 2026-09-22).
DEFAULT_SETTINGS = {
    "service_host": None,
    "http2https": True,
    "display_names": True,
}


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _atomic_write_json(path, obj):
    tmp_path = f"{path}.{os.getpid()}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp_path, path)


def load_domains():
    """{"<domain>": {"enabled": bool}}, empty if never written."""
    return _load_json(DOMAINS_PATH, {})


def save_domains(domains):
    _atomic_write_json(DOMAINS_PATH, domains)


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    settings.update(_load_json(SETTINGS_PATH, {}))
    return settings


def save_settings(settings):
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings)
    _atomic_write_json(SETTINGS_PATH, merged)

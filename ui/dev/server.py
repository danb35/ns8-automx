#!/usr/bin/env python3
#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Local harness for the automx UI: a mock NS8 API serving the built UI
(ui/dist) inside a fake shell (harness.html). Adapted from ns8-dnshelper's
ui/dev.

    python3 ui/dev/server.py [port]        then open http://127.0.0.1:8098/

The automx actions need a live node (mail module, ldapproxy, Traefik,
dnshelper), so they are canned here: a mail server mail1 with three domains,
SOGo, WebTop and Nextcloud, dnshelper managing example.com and example.net.
Settings and per-domain overrides are kept with the module's real
automx.state code in a temporary directory, so the Settings page and the
Domain settings dialog behave as on a node; the DNS records come from the
real automx.dns.expected_records(). Output shapes follow each action's
validate-output.json.

Environment: CORE_CSS=<the NS8 core UI's css/core.css> gives the shell's
styling (see README.md).
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STATE = tempfile.mkdtemp(prefix="automx-ui-")
os.environ["AGENT_STATE_DIR"] = STATE
sys.path.insert(0, os.path.join(ROOT, "imageroot", "pypkg"))
sys.modules["agent"] = types.ModuleType("agent")  # automx.groupware imports it; unused here
from automx import dns, domains as domains_lib, groupware, state  # noqa: E402

state.STATE_DIR = STATE
DIST = os.path.join(HERE, "..", "dist")
CORE_CSS = os.environ.get("CORE_CSS", "")
EVENTS, LOCK = [], threading.Lock()

MODULE_ID = "automx1"
NODE_FQDN = "node.example.com"
MAIL_UUID = "0f6c6c3e-4d1b-4a43-9d0e-2b2f4c1a7e51"
MAIL_DOMAINS = ["example.com", "example.net", "example.org"]
GROUPWARE = [
    {"module_id": "nextcloud1", "kind": "nextcloud", "host": "cloud.example.com",
     "dav_url": "https://cloud.example.com/remote.php/dav/", "activesync_url": None},
    {"module_id": "sogo1", "kind": "sogo", "host": "sogo.example.com",
     "dav_url": "https://sogo.example.com/SOGo/dav/",
     "activesync_url": "https://sogo.example.com/Microsoft-Server-ActiveSync"},
    {"module_id": "webtop1", "kind": "webtop", "host": "webtop.example.com",
     "dav_url": "https://webtop.example.com/webtop-dav/server.php",
     "activesync_url": "https://webtop.example.com/Microsoft-Server-ActiveSync"},
]
# Per domain: which zone dnshelper manages and whether automx may change it
# (None: not managed, DNS is manual), the record status, and the route.
DNS = {
    "example.com": {"zone": "example.com", "allowed": True, "status": "ok", "route": "configured"},
    "example.org": {"zone": None, "allowed": None, "status": "ok", "route": "configured"},
    "example.net": {"zone": "example.net", "allowed": False, "status": "not_permitted", "route": "not_configured"},
}
INSTALLED = {
    "ghcr.io/danb35/automx": [{"id": MODULE_ID, "node": "1", "module": "automx", "ui_name": "",
                               "version": "0.4.0", "source": "ghcr.io/danb35/automx"}],
}


def seed():
    state.save_settings({"dav_module": "sogo1", "activesync_module": "sogo1", "sign_profiles": True})
    state.save_domains({
        "example.com": {"enabled": True},
        "example.org": {"enabled": True, "overrides": {
            "display_names": False, "dav_module": None, "activesync_module": None}},
    })


class Refused(Exception):
    def __init__(self, errors):
        self.errors = errors


def domain_dns(domain):
    info = DNS[domain]
    records = [{**r, "status": info["status"]} for r in dns.expected_records(domain, NODE_FQDN)]
    return {"managed": info["zone"] is not None, "zone": info["zone"], "allowed": info["allowed"], "records": records}


def known(domain):
    if domain not in MAIL_DOMAINS and domain not in state.load_domains():
        raise Refused([{"field": "domain", "parameter": "domain", "value": domain, "error": "domain_not_found",
                        "message": "not a domain of the configured mail instance"}])


def get_configuration(data):
    settings = state.load_settings()
    stored = state.load_domains()
    return {
        "service_host": settings["service_host"],
        "http2https": settings["http2https"],
        "display_names": settings["display_names"],
        "resolve_aliases": settings["resolve_aliases"],
        "sign_profiles": settings["sign_profiles"],
        "signing": {"host": NODE_FQDN, "certificate_type": "internal", "problem": None, "trusted": True}
        if settings["sign_profiles"] else None,
        "dav_module": settings["dav_module"],
        "activesync_module": settings["activesync_module"],
        "groupware": GROUPWARE,
        "enabled_domain_count": sum(1 for f in stored.values() if f.get("enabled")),
        "mail_server": MAIL_UUID,
        "mail_servers": [{"module_uuid": MAIL_UUID, "module_id": "mail1", "ui_name": "", "hostname": "mail.example.com",
                          "user_domain": "example.com", "node": "1", "used_by": None, "groupware": GROUPWARE}],
        "mail_hostname": "mail.example.com",
        "user_domain": "example.com",
        "dnshelper_present": True,
    }


def configure_module(data):
    settings = state.load_settings()
    settings.update({k: v for k, v in (data or {}).items() if k in state.DEFAULT_SETTINGS})
    errors = groupware.unavailable(GROUPWARE, {k: (data or {}).get(k) for k in groupware.SERVICE_OF_SETTING})
    if errors:
        raise Refused(errors)
    state.save_settings(settings)
    return None


def get_domains(data):
    settings = state.load_settings()
    stored = state.load_domains()
    out = []
    for entry in domains_lib.merge(set(MAIL_DOMAINS), stored):
        flags = stored.get(entry["domain"])
        out.append({
            **entry,
            "overrides": state.domain_overrides(flags),
            "settings": state.effective_settings(settings, flags),
            "route_status": DNS[entry["domain"]]["route"] if entry["enabled"] else "not_configured",
            "dns": domain_dns(entry["domain"]),
        })
    return {"dnshelper_present": True, "domains": out}


def set_domains(data):
    stored = state.load_domains()
    for domain, flags in data["domains"].items():
        known(domain)
        stored.setdefault(domain, {})["enabled"] = flags["enabled"]
    state.save_domains(stored)
    time.sleep(1)  # a reconcile takes a while
    return {"route_failures": [], "waiting_for_dns": []}


def set_domain_settings(data):
    domain, overrides = data["domain"], data["overrides"]
    known(domain)
    errors = groupware.unavailable(GROUPWARE, {k: overrides.get(k) for k in groupware.SERVICE_OF_SETTING})
    if errors:
        raise Refused(errors)
    stored = state.load_domains()
    entry = stored.setdefault(domain, {"enabled": False})
    if overrides:
        entry["overrides"] = overrides
    else:
        entry.pop("overrides", None)
    state.save_domains(stored)
    time.sleep(1)
    return {"domain": domain, "overrides": state.domain_overrides(entry),
            "settings": state.effective_settings(state.load_settings(), entry)}


def check_dns(data):
    wanted = [data["domain"]] if data and data.get("domain") else MAIL_DOMAINS
    return {"results": [{"domain": d, "dns": domain_dns(d)} for d in wanted]}


def get_dns_plan(data):
    return {"records": [{**r, "suggested_ttl": 3600} for r in dns.expected_records(data["domain"], NODE_FQDN)]}


def apply_dns(data):
    zone = DNS[data["domain"]]["zone"]
    add = [{"name": dns.dnshelper_relative_name(r["host"], zone), "type": r["type"], "data": r["value"], "ttl": 3600}
           for r in dns.expected_records(data["domain"], NODE_FQDN)]
    return {"dry_run": data["dry_run"], "changes": {"add": add, "remove": []}}


def get_profile_link(data):
    domain = data["domain"]
    regex = domain.replace(".", r"\.")
    snippet = f"""<!-- Paste this where you want a "Download email settings" form.
     Generated by ns8-automx for domain: {domain} -->
<form action="https://autoconfig.{domain}/mobileconfig" method="post"
      style="max-width:22rem;font:14px sans-serif">
  <input type="hidden" name="_mobileconfig" value="true">
  <label for="automx-email">Your email address</label><br>
  <input id="automx-email" name="emailaddress" type="email"
         placeholder="you@{domain}" required
         pattern="[^@\\s]+@{regex}"
         title="Must end in @{domain}"
         style="width:100%;box-sizing:border-box;margin:.4em 0;padding:.4em">
  <button type="submit">Download mail profile</button>
</form>
"""
    return {"url": f"https://autoconfig.{domain}/mobileconfig", "html_snippet": snippet}


def get_status(data):
    return {
        "instance": MODULE_ID, "ui_name": "", "node": "1", "node_ui_name": "",
        "services": [{"name": "automx", "active": True, "enabled": True, "failed": False},
                     {"name": "automx-aliases", "active": False, "enabled": False, "failed": False}],
        "images": [{"name": "ghcr.io/danb35/automx-app:0.4.0", "size": "214 MB", "created": "2026-11-10 16:30:00 +0000 UTC"}],
        "volumes": [],
    }


MODULE_ACTIONS = {
    "get-configuration": get_configuration, "configure-module": configure_module, "get-domains": get_domains,
    "set-domains": set_domains, "set-domain-settings": set_domain_settings, "check-dns": check_dns,
    "get-dns-plan": get_dns_plan, "apply-dns": apply_dns, "get-profile-link": get_profile_link,
    "get-status": get_status,
}
CLUSTER_ACTIONS = {
    "list-installed-modules": lambda data: INSTALLED,
    "list-backup-repositories": lambda data: {"repositories": []},
    "list-backups": lambda data: {"backups": []},
}


def run(kind, module_id, body):
    action, data, event = body["action"], body.get("data"), body["extra"]["eventId"]
    time.sleep(0.15)  # a task takes a moment
    ev = {"action": action, "eventId": event, "type": "completed", "output": None}
    try:
        handlers = CLUSTER_ACTIONS if kind == "cluster" else MODULE_ACTIONS
        ev["output"] = handlers[action](data)
    except Refused as e:
        ev.update(type="validation-failed", errors=e.errors, output=None)
    except Exception as e:  # unknown action, bug: show it as a failed task
        print("harness error", kind, repr(module_id), action, file=sys.stderr)
        traceback.print_exc()
        ev.update(type="aborted", output={"error": repr(e)})
    with LOCK:
        # kept, not handed out once: a dropped response or a second viewer must not lose results
        ev["seq"] = len(EVENTS) + 1
        EVENTS.append(ev)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/events":
            after = int((parse_qs(urlparse(self.path).query).get("after") or ["0"])[0])
            with LOCK:
                out = [e for e in EVENTS if e["seq"] > after]
            return self.send(200, out)
        if path == "/":
            return self.send(200, open(os.path.join(HERE, "harness.html"), "rb").read(), "text/html")
        if path == "/cluster-admin/css/core.css" and os.path.isfile(CORE_CSS):
            return self.send(200, open(CORE_CSS, "rb").read(), "text/css")
        if path.startswith("/app/"):
            rel = path[len("/app/"):] or "index.html"
            full = os.path.normpath(os.path.join(DIST, rel))
            if full.startswith(os.path.normpath(DIST)) and os.path.isfile(full):
                ctype = {".js": "text/javascript", ".css": "text/css", ".html": "text/html",
                         ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml"
                         }.get(os.path.splitext(full)[1], "application/octet-stream")
                return self.send(200, open(full, "rb").read(), ctype)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        parts = self.path.strip("/").split("/")  # api/module/<id>/tasks | api/cluster/tasks
        if parts[:2] == ["api", "module"] and parts[-1] == "tasks":
            kind, module_id = "module", parts[2]
        elif parts[:2] == ["api", "cluster"] and parts[-1] == "tasks":
            kind, module_id = "cluster", ""
        else:
            return self.send(404, {"error": "unknown api"})
        threading.Thread(target=run, args=(kind, module_id, body), daemon=True).start()
        self.send(200, {"result": "ok"})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8098
    seed()
    print(f"state dir {STATE}\nopen http://127.0.0.1:{port}/", flush=True)
    try:
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    finally:
        shutil.rmtree(STATE, ignore_errors=True)

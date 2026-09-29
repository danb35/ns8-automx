# ns8-automx

Email client autoconfiguration for [NethServer 8](https://github.com/NethServer/ns8-core)
mail domains, built on [croessner/automx](https://github.com/croessner/automx). Clients
that are given only an email address (Thunderbird via Mail Autoconfig, Outlook and phones'
Exchange setup via Microsoft Autodiscover, Apple devices via a `.mobileconfig` profile,
optionally signed with the server's own certificate) discover the IMAP and SMTP settings of
the NS8 mail server on their own, with the correct login name and display name looked up
from the domain's accounts provider (OpenLDAP or Samba AD), also for a mail alias. The
calendars and contacts (CalDAV/CardDAV) or ActiveSync server of an installed Nextcloud,
SOGo or WebTop can be published along with mail.

**Administering it?** The [user guide](docs/USER-GUIDE.md) explains enabling domains,
publishing their DNS records (with or without dnshelper), settings, and sharing a
download link with your users. This README is for people who build, test or work on the
module itself.

See [DESIGN.md](DESIGN.md) for the full design, including the NS8 platform facts it
depends on, why it uses automx's `script` LDAP backend instead of the native one, and the
findings from testing it against real NS8 nodes.

## Status

Every step of [DESIGN.md](DESIGN.md)'s design is implemented and has been exercised on
real NS8 nodes, across six separate real-node passes: the core autoconfig/Autodiscover/
mobileconfig path against both OpenLDAP (`rfc2307`) and Samba AD (`ad`) accounts
providers; the manual (resolver-based) and dnshelper-backed DNS flows, including
`not_permitted`, `conflict`, `unmanaged`, create, overwrite and the dnshelper-coverage-
added-later ordering case; the alias-address fallback (aliases resolve to their owner's
login since 0.2.0); the LDAP-unreachable fallback; Traefik
route and certificate creation; disabling a domain; backup and restore into a new
instance; and module removal. A final pass reran the whole stack (accounts provider,
mail, automx, dnshelper) from scratch on a freshly reverted node with no new findings.
See DESIGN.md section 9 for the detailed log of what was tested and what each real-node
pass found and fixed.

A seventh pass, against a real internet-accessible node with a real public domain and a
real Let's Encrypt CA, found and fixed two real issues that the earlier LAN-only passes
couldn't have surfaced: an SRV-record bug in ns8-dnshelper's Cloudflare provider (fixed
upstream, released as dnshelper 0.2.1), and a design flaw where a domain's Traefik routes
were created before its DNS existed, permanently losing their one shot at a Let's Encrypt
certificate. Routes are now deliberately held back until DNS is ready (DESIGN.md 5.6).

Real client testing is done: Betterbird (a Thunderbird fork, Autoconfig), Outlook LTSC
(Autodiscover) and Apple Mail on macOS (`.mobileconfig`) have all been confirmed working
against the live node. Parula has also been confirmed working, though which autodiscovery
mechanism it used is not known. This also resolved the `http2https` default (DESIGN.md VERIFY item
6): kept at its default `true`, since no client needed a plain-HTTP fallback.

`tests/integration/` has been run against a real node (an eighth pass, which found and fixed a
readiness gap and a redundant restart after first enabling a domain). It does not yet cover route
and certificate creation, dnshelper, or Samba AD, which need a node with those set up and inbound
internet access; those were exercised manually in the earlier passes.

v2 (0.2.0, see DESIGN.md section 2) adds CalDAV/CardDAV and ActiveSync from Nextcloud,
SOGo or WebTop, alias resolution, signed Apple profiles, and the capitalized
`/Autodiscover/Autodiscover.xml` path (automx is patched to serve it until upstream releases
the change). It was tested on Rocky 9 and Debian 13 nodes, a public node with real Let's
Encrypt certificates, an iPhone (iOS 26.7) and a Mac (macOS 15.8):

- The signed profile shows as signed on iOS and without the "Unverified" warning on macOS,
  and its Nextcloud calendars and contacts work.
- An iPhone's own Exchange account setup found SOGo's ActiveSync server through automx and
  synced a calendar event, asking for the password once (a profile asks once per account).
  It first tried Autodiscover v2, which automx does not serve, then used the capitalized
  Autodiscover path: the first real client seen on it.
- Nextcloud is offered only when it runs on the same node as automx.

Still unconfirmed with real clients: SOGo and WebTop calendars and contacts through the
profile's CalDAV/CardDAV accounts, Thunderbird with an ActiveSync entry in Autoconfig, and
Outlook with ActiveSync. See DESIGN.md section 2 for the details.

Not in scope: PACC, Autodiscover v2, several mail instances at once. See DESIGN.md
section 2 and 12.

## Install

### From the Software center (recommended)

automx is published in the software repository at
[danb35.github.io/ns8-repomd](https://danb35.github.io/ns8-repomd/) (source:
[danb35/ns8-repomd](https://github.com/danb35/ns8-repomd)), which also carries
[dnshelper](https://github.com/danb35/ns8-dnshelper). Add it to the cluster once:

1. In the cluster admin UI, open **Settings → Software repositories** and click **Add repository**.
2. Enter a name (for example `danb35`) and the URL `https://danb35.github.io/ns8-repomd/`, leave
   **Status** enabled, and click **Add repository**. NS8 warns about third-party repositories;
   this one only lists the images published from this GitHub account.
3. Open the **Software center**, find **automx**, and click **Install**.

Or add the repository from a shell on the leader node:

    api-cli run add-repository --data '{"name":"danb35","url":"https://danb35.github.io/ns8-repomd/","status":true}'

With the repository added, new releases are offered as updates in the Software center like any
other app. They are usually listed within a few minutes of being published.

### From the command line

Instantiate the module with:

    add-module ghcr.io/danb35/automx:latest 1

The output of the command returns the instance name:

    {"module_id": "automx1", "image_name": "automx", "image_url": "ghcr.io/danb35/automx:latest"}

To install a particular release instead of the newest build, use its tag in place of `latest`,
for example `ghcr.io/danb35/automx:0.1.1`.

Then open the module's page in the NS8 admin UI, or see the
[user guide](docs/USER-GUIDE.md) for the full walkthrough.

## Actions

Each action has `validate-input.json` and `validate-output.json` under
`imageroot/actions/<action>/`. Schemas accept `null` as well as `{}` for the
argument-less ones, since the admin UI sends no payload.

| Action | Purpose |
|---|---|
| `configure-module` | Settings: service host override (default: this node's own FQDN), `http2https` default, `display_names` toggle, and the groupware modules (`dav_module`, `activesync_module`) whose endpoints are published. Starts the service once at least one domain is enabled. |
| `get-configuration` | Settings plus a summary (enabled domain count, mail hostname, user domain, dnshelper presence) for the Status page, and the groupware modules that can provide CalDAV/CardDAV or ActiveSync. |
| `get-domains` | The mail module's domains merged with the module's own enable/disable state: enabled flag, route status, DNS status per record, orphan flag. |
| `set-domains` | Enable or disable one or more domains; applies Traefik routes, renders `automx.conf`, validates it, reloads the service. |
| `check-dns` | Recompute DNS status for one domain (dnshelper path if it covers the zone, resolver path otherwise). |
| `apply-dns` | For one domain: `create` (missing records) or `overwrite` (conflicting ones), each after a `dry_run` preview. dnshelper only. |
| `get-dns-plan` | The exact records to create, for the manual (no-dnshelper) path. |
| `get-dnshelper-status` | Whether dnshelper is present and, per domain, whether its zone is managed and whether this module is allowed to change it — what the UI needs to say exactly what's missing. |
| `get-profile-link` | For one enabled domain: automx's own unauthenticated mobileconfig form URL and a ready-to-embed HTML snippet. No state change, no call to automx itself. |

## How it fits together

- **Mail domains and users**: `automx.conf` is rendered from the mail module's own
  domains and hostname (`mail@any:mailadm`, the only consumer role ns8-mail offers —
  broader than needed, but automx never calls the credential/BCC/relay actions it also
  grants) and from the domain's LDAP/AD parameters via `agent.ldapproxy.Ldapproxy()`
  (`cluster:accountconsumer`). See DESIGN.md 3.1–3.3.
- **Login/display-name lookup** does not use automx's native `backend = ldap`: it cannot
  express "match the login attribute against the local part, else match `mail` against
  the full address" in a single filter, and it hard-fails instead of falling back on a
  miss. `imageroot/bin/automx-ldap-lookup`, invoked through automx's `script` backend,
  does the two-step lookup itself and always exits 0 with a fallback (the bare address,
  no display name) on a miss or an unreachable directory. A mail alias that delivers to one
  user is looked up as that user, from a map `imageroot/bin/refresh-aliases` builds from the
  mail module's addresses every 15 minutes. See DESIGN.md 3.3 and 2.
- **Traefik routes** (`traefik@node:routeadm`) publish `autoconfig.<domain>` and
  `autodiscover.<domain>` for each enabled domain, plus routes on the node's own FQDN
  restricted to the Autodiscover path in both spellings (SRV records point there). See
  DESIGN.md 3.4/4.4.
- **Profile signing** (optional) reads the service host's certificate from Traefik
  (`traefik@node:certadm`) and has automx sign `.mobileconfig` profiles with it; a
  certificate automx can't use is skipped with the reason shown in Settings. See
  `imageroot/pypkg/automx/signing.py`.
- **Groupware** (CalDAV/CardDAV, ActiveSync) is read from the chosen module's own
  environment in Redis (SOGo, WebTop) or its Traefik route (Nextcloud, same node only),
  and offered only when it is bound to the mail instance's user domain (and, for
  ActiveSync, uses the same mail module). See `imageroot/pypkg/automx/groupware.py`.
- **DNS records** (`autoconfig.<domain>`, `autodiscover.<domain>`,
  `_autodiscover._tcp.<domain>`) are managed directly through
  [ns8-dnshelper](https://github.com/danb35/ns8-dnshelper)
  (`dnshelper@cluster:dnswriter`) when it is present and covers the zone, or shown as
  copyable instructions otherwise. See [Using dnshelper](#using-dnshelper) below and
  DESIGN.md section 5.

## Using dnshelper

dnshelper is optional. If it isn't installed, `get-domains`/`check-dns` resolve the
records from a public DNS server instead and the UI shows what to create by hand.

If it is installed, this module still starts out with **no access**: dnshelper denies
every module everything until an administrator adds a rule for it. Add one on
dnshelper's own Access page, or with `set-policy`:

```json
{"caller": "module/automx1", "zones": ["example.com"], "access": "write",
 "names": ["autoconfig", "autoconfig.*", "autodiscover", "autodiscover.*",
           "_autodiscover._tcp", "_autodiscover._tcp.*"],
 "types": ["CNAME", "SRV"]}
```

(Replace `module/automx1` with this module's actual instance id, and list the zones
dnshelper should let it manage — `["*"]` for all of them.) The Domains page's DNS status
dialog shows this same suggested rule, with the real zone name filled in, whenever a
domain's zone is managed by dnshelper but not yet covered by a rule.

That rule only covers *creating* CNAME/SRV records or replacing a same-type CNAME/SRV
value. **Overwriting a record of a different type** (for example, an existing A record
where automx wants a CNAME) additionally needs a rule that also allows the conflicting
type at the same names — add it, or `types: ["*"]`, if you expect that case. See
DESIGN.md 5.3.6.

Access is re-checked live on every `get-domains`/`check-dns` call, not cached — so
installing dnshelper (or adding zone coverage, or granting the rule) after this module
was already configured takes effect immediately, with no need to disable and re-enable
the domain. Confirmed on a real node; see DESIGN.md section 9.

## Backup and restore

**What is backed up** (`imageroot/etc/state-include.conf`): `state/domains.json` (the
enable/disable flag per domain) and `state/settings.json`. `automx.conf` itself is not
backed up — it's a pure function of these two files plus live discovery data (mail
domains, LDAP parameters), regenerated on every service start, and it contains the LDAP
bind password.

Restore re-runs the renderer, re-creates Traefik routes and DNS status, and tolerates
the mail module or accounts provider not being present yet. It has been exercised on a
real node: back up, restore into a *new* instance (not overwriting the original), and
confirm the restored instance's service, domain state, settings and actual autoconfig
responses are all correct — see DESIGN.md section 9 for the details.

## Admin UI

Vue 2 with Carbon and `ns8-ui-lib`, in `ui/`. Four pages besides About: Status, Domains
(the DNS status dialog and the profile-link dialog live here), and Settings. See the
[user guide](docs/USER-GUIDE.md) for what each one does.

```bash
cd ui && yarn install && yarn build
```

## Development

Agent guidance for this repository is in [AGENTS.md](AGENTS.md), [AGENTS-backend.md](AGENTS-backend.md)
and [AGENTS-frontend.md](AGENTS-frontend.md); read the matching one before working in
`imageroot/` or `ui/`. Consuming dnshelper from this module's own code follows the
contract in `ns8-dnshelper`'s own README, checked out alongside this repository — see
`CLAUDE.md` for the exact path convention this repository expects.

The automx application itself is built from source in `build-images.sh`, pinned to a
specific upstream tag: the published `ghcr.io/croessner/automx` image never installs
automx's own `ldap` extra, so it can't be used as-is. See DESIGN.md 4.5 for why, and for
what was confirmed by actually building and running the resulting image locally.

## Testing on a node

`tests/integration/` follows `ns8-dnshelper`'s own `tests/integration/` structure: a
re-runnable script against a real node. Unlike dnshelper's version, it does not set up
the mail domain or accounts provider itself — see `tests/integration/README.md` for what
the node must already have. It installs the published image and covers install,
domains, the LDAP lookup, the capitalized Autodiscover path, alias resolution, DNS status,
backup/restore and removal, and passes on Rocky 9 and Debian 13. The route/certificate,
dnshelper, Samba AD, groupware and signing scenarios were exercised manually, as recorded in
DESIGN.md sections 2 and 9.

The Robot suite in `tests/` is the smoke test CI runs (`test-module.sh`):

```bash
./test-module.sh <NODE_ADDR> ghcr.io/danb35/automx:latest
```

It runs on a throwaway CI node with no mail module present, so it confirms
`set-domains` degrades cleanly (a `validation-failed` on an unknown domain, not a crash)
rather than exercising the full enable-a-domain path, which needs the real infrastructure
`tests/integration/` and the manual passes in DESIGN.md cover instead.

## UI translation

English is the source language, in `ui/public/i18n/en/translation.json`. German, Spanish,
French, Italian, Portuguese and Brazilian Portuguese (matching `ns8-dnshelper`'s target
languages) were translated directly from it and have not been reviewed by native speakers.
Basque (`eu`) still carries the ns8-kickstart template's placeholder text, same gap as
dnshelper's own `eu` locale — not yet translated.

Not yet set up for this repository: [Weblate](https://hosted.weblate.org/projects/ns8/),
for community translation and native-speaker review going forward.

- add the [GitHub Weblate app](https://docs.weblate.org/en/latest/admin/continuous.html#github-setup)
  to your repository
- add your repository to [hosted.weblate.org](https://hosted.weblate.org) or ask a
  NethServer developer to add it to the ns8 Weblate project

# ns8-automx: Design

Status: draft v1, 2026-09-20. Audience: the developer (human or agent) implementing the module. Read `AGENTS.md`, `AGENTS-backend.md` and `AGENTS-frontend.md` first; this document assumes their conventions (pinned image tags, authorizations as labels in `build-images.sh`, Renovate, Robot tests, Vue 2 + Carbon UI).

Items marked **VERIFY** are things the design depends on that were not confirmed from documentation while writing this. Resolve each before or during implementation and record the answer in this file.

## 1. Purpose

Provide email client autoconfiguration for NethServer 8 mail domains, using [croessner/automx](https://github.com/croessner/automx) (automx 3.0, a FastAPI/ASGI rewrite, currently beta). Clients (Thunderbird, Outlook, Apple Mail) that are given only an email address find the IMAP and SMTP settings of the NS8 mail server by themselves.

The module:

1. reads the mail domains configured in the NS8 mail module;
2. lets the administrator enable or disable autoconfiguration per domain;
3. looks up users in the domain's accounts provider (OpenLDAP or Samba AD) so that clients receive the right login name and display name;
4. publishes `autoconfig.<domain>` and `autodiscover.<domain>` through Traefik, with certificates;
5. optionally creates and checks the DNS records clients need, using `ns8-dnshelper` when it is present.

## 2. Scope

### In scope for v1

- Protocols: Mail Autoconfig (Thunderbird), Microsoft Autodiscover (Outlook), Apple `.mobileconfig`.
- One mail module instance, one shared user domain (see 3.1).
- Per-domain enable/disable, default disabled.
- LDAP lookup for login name and display name, for both `rfc2307` (OpenLDAP) and `ad` (Samba AD) providers.
- Traefik routes and certificates for `autoconfig.<domain>` and `autodiscover.<domain>` for each enabled domain.
- DNS: CNAME and SRV records, checked and created through dnshelper if available, checked and shown for manual creation otherwise.
- Admin UI: status, domains table, settings.

### Out of scope for v1 (possible later)

- PACC (`_ua-auto-config` TXT record and JSON). It is an Internet-Draft and its TXT digest is byte-sensitive to the served configuration.
- Autodiscover v2 (experimental in automx), OAuth metadata, EWS/ActiveSync/JMAP/CalDAV/CardDAV publication.
- Several mail instances at once.
- Resolving mail aliases to login names (see 3.3, phase 2).
- Mobileconfig CMS signing (needs a certificate and key; the profile is served unsigned in v1).

## 3. Facts about NS8 that shape the design

### 3.1 Mail domains and users

- A mail module instance has one `user_domain` (the LDAP account domain) and a list of mail domains. All mail domains of an instance share that one user base. NS8 mail has no per-domain tenant isolation. Example from the mail README: mail domain `example.com` with user domain `ad.example.com`.
- The IMAP/SMTP login is the bare username. A user `dan` can log in as `dan` or `dan@<domain>`.
- Users can have free-form mail aliases (for example `dan.brown@<domain>`) but cannot log in with an alias.
- Consequence: an address typed into a client is not always a valid login. For the user's own primary address (`dan@domain`) the address works as the login. For an alias it does not, and the correct login (`dan`) has to come from a lookup.

### 3.2 Service discovery

- Mail endpoints are registered in Redis as HASH keys `module/mail<N>/srv/tcp/imap` (port `143`) and `module/mail<N>/srv/tcp/submission` (port `10587`), with fields `host`, `port`, `node`, `user_domain`, `uuid`. **Confirmed** (read of `NethServer/ns8-mail`, `imageroot/actions/configure-module/90publish_srv_keys`): these are explicitly internal, unauthenticated endpoints, not what a client is told to connect to.
- **Confirmed**: `get-configuration` (`imageroot/actions/get-configuration/20read`) is the action that returns the public hostname, as `hostname` (`os.environ['POSTFIX_HOSTNAME']`, i.e. Postfix's `myhostname`/TLS-cert name — use this as `imap_server`/`smtp_server`), alongside `user_domain`. **There is no action, config field, or Redis key anywhere in ns8-mail that reports public IMAP/SMTP ports** — 993 (IMAPS, `dovecot/README.md`) and 465 (SMTPS, `postfix/README.md`) are fixed, hardcoded constants in the sub-container images, never surfaced as configuration. This confirms decision log #11: the 993/465 defaults are not overridable and item 1 of the VERIFY list needs no further port check.
- The `mail-settings-changed` event is published in the same `90publish_srv_keys` script. **Confirmed** payload: `{"reason", "module_id", "module_uuid", "node_id"}`, where `reason` is `AGENT_TASK_ACTION` (e.g. `configure-module`) or `"unknown"`. It fires on every `configure-module` run; verify during implementation that domain add/remove also routes through `configure-module` (and so fires this event) rather than a separate, silent action.
- The mail module has a `list-domains` action (`module/mailN/list-domains`, no input). **Confirmed** output: a JSON array of objects matching the `mail-domain` schema in `imageroot/validator-definitions.json` — `domain` (required), `addusers`, `addgroups`, `addaliases`, `catchall`, `bccaddr`, `description`. There is no `user_domain` per domain; it comes from `get-configuration` instead, one per instance (matches 3.1). **Confirmed, and worse than hoped**: `mailadm` is the *only* consumer role ns8-mail defines (`imageroot/actions/create-module/30grants`); its `get-*`/`list-*` wildcard covers `list-domains`/`get-configuration`, but the same role also grants `reveal-master-credentials`, `set-always-bcc`, and the relay-rule actions. No narrower role exists upstream. Decision needed: accept `mail@any:mailadm` and document in our README that automx never calls the credential/BCC/relay actions despite being able to, or file a narrower-role request against `NethServer/ns8-mail` (out of scope for this repo, like dnshelper changes go in dnshelper's repo).

### 3.3 Accounts provider

- Use `agent.ldapproxy.Ldapproxy()`: `get_domains_list()`, `get_domain(<user_domain>)`. The result holds a local endpoint (ldapproxy listens on `127.0.0.1`, no TLS needed on that hop), bind credentials, base DN, schema (`rfc2307` or `ad`).
- The module image needs `org.nethserver.authorizations=cluster:accountconsumer`, and calls `agent.bind_user_domains([user_domain])`.
- A container on a private podman network reaches ldapproxy at `10.0.2.2` if started with `--network=slirp4netns:allow_host_loopback=true`. With `--network=host` it is `127.0.0.1` (see 4.1).
- Events: `user-domain-changed` (payload `{"domains": [...]}`) and `module-domain-changed`.
- Use `Ldapproxy.get_ldap_users_search_filter_clause()` so hidden users are honored.

Attribute mapping:

| Provider schema | Login | Address | Display name |
|---|---|---|---|
| `rfc2307` (OpenLDAP) | `uid` | `mail` | `cn` |
| `ad` (Samba AD) | `sAMAccountName` | `mail` | `displayName` |

Lookup rule for an address `local@domain`, in order:
1. an entry whose login attribute equals `local` (covers `dan@domain` and `dan`);
2. an entry whose `mail` attribute equals the full address.

Aliases defined only in the mail module (its `list-addresses` data) are not in LDAP and are **not resolved in v1**. A user who types an alias gets the static fallback (below) and may need to enter their login by hand. Phase 2 can generate an alias map from `list-addresses` at config-render time and serve it through automx's bounded `script` backend.

**RESOLVED, and this changes the implementation approach** (2026-09-22, read of `croessner/automx` source, `src/automx/backends.py` + `src/automx/configuration.py`, commit `627e7a6`, matching release `v3.0.0-beta.3`):

- automx's native `backend = ldap` substitutes only `%s` (the full, escaped client-supplied email address) into the `filter` INI key — there is no `%u`/`%d` (local-part/domain) substitution available inside an LDAP backend's `filter`, unlike the `script` backend which does get `%u`/`%d` via `BackendContext.expand()`. **The two-step lookup rule above (match login attribute against the local-part, else match `mail` against the full address) cannot be expressed as a single native-LDAP `filter` string at all** — not just for phase-2 aliases, but for the v1 rule as written. A filter can only search by the literal address the client typed (e.g. `(|(uid=%s)(mail=%s))` searches for `uid` or `mail` equal to the *full* `dan@domain`, which never matches a bare `uid=dan`).
- On backend failure — no LDAP host reachable, or a search with no matching rows — `LDAPBackend.resolve()` raises `BackendError`, which `configuration.py` re-raises as `ConfigurationError`. **This aborts the whole request; automx does not fall back to `[global]`'s static values.** Autoconfig and Mobileconfig return HTTP 400 JSON (`{"error": "invalid_request", ...}`), no document at all; only the Autodiscover endpoint returns a real (error) XML body. The desired "static default, login `%EMAILADDRESS%`, no display name" fallback does **not** happen automatically.
- `reqcert` (certificate verification) is hardcoded to `demand` — not actually configurable — but only applies when TLS is negotiated. Set `usetls = no` and use an `ldap://` (not `ldaps://`) URI for the ldapproxy hop, and `reqcert` never comes into play; this is compatible with the plaintext loopback endpoint.

**Decision needed**: given the native `backend = ldap` can neither express the login-attribute-or-mail lookup rule nor give the desired fallback behavior, v1 should use automx's `script` backend instead of `backend = ldap` — a small, bounded (no shell, per automx's own README rule on the `script` backend) Python script that: reads `%u`/`%d`/`%s` from automx, does the two-step lookup itself via `Ldapproxy` (3.3 above), and always prints a result — falling back to `%EMAILADDRESS%`/no display name on a miss or an LDAP error — so automx always has *something* to render instead of hard-failing the request. This folds the phase-2 alias-map idea and the v1 lookup rule into the same mechanism (one script, one `backend = script` stanza), rather than treating `script` as a phase-2-only escalation. Revise 4.3's config sketch and the "phase 2" framing in section 12 accordingly during implementation.

### 3.4 Traefik

- The module needs `traefik@node:routeadm` and creates routes with the Traefik `set-route` action (host, upstream URL, `lets_encrypt`, `http2https`). The upstream URL is `http://127.0.0.1:<TCP_PORT>`, where `<TCP_PORT>` is the node port allocated to this module (`org.nethserver.tcp-ports-demand=1`). That address is the node's loopback: the NS8 network documentation has web modules publish the container port on host loopback (`podman run --publish 127.0.0.1:${TCP_PORT}:<container port>`) and Traefik, which runs on the same node, reaches it there. It is not the container's own localhost; see 4.1 for what automx binds inside the container. Routes are per host: N enabled domains means 2N routes plus any route for the node FQDN (see 4.4). Route instance names must be unique per host, for example `<module_id>-autoconfig-<domain>`.

  **RESOLVED** (2026-09-22, read of `NethServer/ns8-traefik`, current `main`). `set-route` fields, confirmed against `imageroot/actions/set-route/validate-input.json` and `20writeconfig`: `instance` (required, the idempotency key — route config is written to `configs/<instance>.yml`; calling `set-route` again with the same `instance` merges new fields into the existing route, so it's safe to call repeatedly), `url`, `host` (nullable), `path` (nullable — a path-prefix filter, matched with or without a trailing slash), `priority` (int), `lets_encrypt`, `lets_encrypt_check` (default `false`), `lets_encrypt_cleanup` (default `false`), `http2https`, `strip_prefix`, `slash_redirect`, `skip_cert_verify`, `ip_allowlist`, `headers`, `forward_auth`. `delete-route` takes `instance` (required) and `lets_encrypt_cleanup` (optional). Three rule tiers by default priority: host+path (3) > host-only (2) > path-only (1); NS8 core's own `cluster-admin` route (`ns8-traefik/imageroot/actions/create-module/60cluster_admin`) is a real precedent for a path-only route with no `host` at all, at an explicit `priority: 100000`. **On module removal, ns8-traefik's `imageroot/events/module-removed` handler deletes every route config whose filename contains the removed module's `module_id`** — so `<module_id>-autoconfig-<domain>`-style instance names are auto-cleaned; no explicit `delete-route` calls are needed in our own `destroy-module`.
- Let's Encrypt HTTP-01 needs the hostname to already resolve to the node. **RESOLVED**: there is no NS8-level retry/backoff for "DNS not ready yet." With `lets_encrypt_check: true`, `set-route` validates synchronously (`ns8-traefik/imageroot/pypkg/cert_helpers.py::request_new_certificate`, one attempt, ~60s poll) and fails the whole action (`newcert_acme_error`) without writing the route if the cert can't be obtained in that window — matching §5.6's "mark the domain waiting for DNS, don't create the route yet" design. With `lets_encrypt_check` left `false` (its default), the route is written immediately and Traefik's own built-in ACME resolver retries in the background indefinitely, with no NS8-level progress visibility beyond the `certificate-changed` event. **Also confirmed**: ns8-core's Python `agent.set_route()` helper defaults to `error_passthrough=True`, which calls `sys.exit()` on any ACME failure and aborts the whole calling action — pass **`error_passthrough=False`** (or call the raw `set-route` action) so a DNS-not-ready failure becomes a handled status update in our own `set-domains`/`check-dns` flow instead of crashing the action.
- The automx documentation says to forward only its documented paths and never a client-supplied base URL. **RESOLVED** (2026-09-22, read of `croessner/automx` `src/automx/app.py`, commit `627e7a6`): the actual routes are `GET /mail/config-v1.1.xml`, `GET /.well-known/autoconfig/mail/config-v1.1.xml` (Autoconfig), `POST /autodiscover/autodiscover.xml` (Autodiscover — automx tells Outlook vs. MobileSync apart by parsing the POSTed XML body, not by path), and `GET /mobileconfig` (serves an HTML download form) plus `POST /mobileconfig` (serves the actual profile; form-urlencoded body, not a query string — see 7.1). **automx registers no capitalized `/Autodiscover/Autodiscover.xml` route at all** — Outlook clients that request the capitalized form get a 404 from automx unless Traefik rewrites the path to the lowercase one first. Since Traefik path-prefix matching is case sensitive, our route (or a Traefik middleware on it) must rewrite `/Autodiscover/*` → `/autodiscover/*` before forwarding, not just allow both prefixes through unchanged.

### 3.5 dnshelper

Repository: `danb35/ns8-dnshelper`, release 0.2.0 at time of writing (2026-09-21). The consumer contract below is from the 0.1.x README; the 0.2.0 release notes list no consumer API changes (new: Core-Networks provider, an admin Records page, a user guide), but re-check the README when implementing. Consumer contract:

- Grant: `--label="org.nethserver.authorizations=dnshelper@cluster:dnswriter"`. The label is harmless if dnshelper is absent; ns8-core re-applies grants when dnshelper is installed later.
- Detect: `agent.list_service_providers(rdb, 'dnshelper')`. Empty list means absent. Call the default instance (`cluster/default_instance/dnshelper`), typically `module/dnshelper1`.
- Actions: `has-zone` (zone or host name; returns `{managed, zone, allowed}`), `list-zones`, `get-records`, `append-records`, `set-records` (default `merge`, or `rrset`), `delete-records`; all write actions accept `dry_run`. Record shape `{name, type, ttl, data}` with names relative to the zone (`@` for apex), SRV data as `"priority weight port target"`.
- Access is default deny. An administrator must add a policy rule naming the caller (`module/<automx id>`), zones, record names and types. `has-zone` returns `allowed: false` until then. A delete without a type needs a rule with type `*`.
- dnshelper refuses a CNAME at the apex or beside other records, and never touches apex NS/SOA.
- Errors arrive as NS8 `validation-failed` with codes `not_permitted`, `zone_not_found`, `conflict`, `forbidden`, `auth_failed`, `unsupported`, `invalid_request`, `unknown_provider`. Provider timeouts fail the step.
- Speed: every call reads the zone first; some providers take 8-15 seconds per call. Never call in a loop per record; batch per zone.
- Event `service-dnshelper-changed` fires when zones are added, changed or removed.

## 4. Architecture

### 4.1 Components

- One rootless podman container running the pinned automx image (`automx serve`), config mounted read-only. It has `/health/live` and `/health/ready`, which the systemd unit uses for readiness.
  - **Networking (default: private network namespace).** The unit runs `podman run ... --publish 127.0.0.1:${TCP_PORT}:<container port> --network=slirp4netns:allow_host_loopback=true ...`. Inside the container automx must listen on a non-loopback address (`automx serve --host 0.0.0.0 --port <container port>`): a listener on the container's own `127.0.0.1` cannot be reached through the published port, and upstream's example `--host 127.0.0.1` is for running it directly on a host. Exposure stays limited because the published port is bound to the node's loopback only.
  - From inside this network namespace, ldapproxy is at `10.0.2.2:<ldap port>`, not `127.0.0.1` (3.3). Health checks and the Traefik route use the published loopback port on the node.
  - **Alternative: `--network=host`.** automx listens directly on `127.0.0.1:${TCP_PORT}`, ldapproxy is at `127.0.0.1`, and no port proxy is involved (the NS8 docs note this is faster). Trade-off: no network isolation from the node's loopback services. Choose one during implementation; the default above is the isolated option and matches the NS8 web-module pattern.
  - **File ownership.** The upstream image runs as UID 10001. In a rootless podman container the host module user maps to root inside, so files the module writes (`automx.conf`, mode 0600, containing the LDAP bind password) may be unreadable by UID 10001. Resolve with `--userns=keep-id` and a matching `--user`, or run the container process as the mapped module user, and confirm the read-only root filesystem and `/tmp` tmpfs still work (**VERIFY**).
- A renderer (Python, in `imageroot/bin/`) that builds `automx.conf` from module state plus discovery data. It is a pure function of its inputs so it can be unit-tested with golden files and checked with `automx config validate`.
- Actions and event handlers (Python) for the admin API.
- Traefik routes managed by the module.
- Vue 2 admin UI.

### 4.2 Module state

Source of truth for domains is the mail module. The module stores only what it owns, in `state/`:

- `state/domains.json`: `{"<domain>": {"enabled": true|false}}`. New mail domains default to disabled. A domain that disappears from the mail module is dropped from generated config and routes; the stored flag is kept and reported as "orphaned" in the UI until the administrator removes it.
- `state/environment`: standard NS8 file (ports, image reference).
- No secrets in Redis or `state/environment`. The LDAP bind password only appears in the rendered `automx.conf`, which is regenerated on every service start, written with mode 0600 and excluded from backup.

Backup (`imageroot/etc/state-include.conf`): `state/domains.json` and any settings file. Restore re-runs the renderer, re-creates routes and re-checks DNS; it must tolerate the mail module or accounts provider not yet being present.

### 4.3 Configuration rendering

Inputs: enabled domains, mail hostname and public ports, user domain and LDAP parameters, node FQDN. Output: one INI file.

Sketch (illustrative; take the exact LDAP key names from the automx configuration reference and its `contrib/e2e/automx.conf`, **VERIFY**):

```ini
[automx]
provider = <node fqdn>
domains = example.com, example.org      ; enabled domains only
autodiscover_v2 = no

[global]
backend = ldap
imap = yes
imap_server = <mail hostname>
imap_port = 993
imap_encryption = ssl
imap_auth = plaintext
smtp = yes
smtp_server = <mail hostname>
smtp_port = 465
smtp_encryption = ssl
smtp_auth = plaintext
; ldap_* keys: local ldapproxy endpoint, bind DN/password, base DN, search filter
;   (login attr OR mail attr, per 3.3), returned variables for login and display name
```

Rules:

- **Client-facing ports/encryption default to implicit TLS on the standard secure ports: IMAPS 993 and SMTPS 465** (both `ssl`, not `starttls`), regardless of what the internal `srv/tcp` Redis keys expose (those are unauthenticated internal endpoints on other ports, not what a client is told to connect to; see 3.2). Use these fixed defaults unless the mail module's own configuration explicitly reports different public-facing ports for the mail hostname (**VERIFY** as part of item 1: confirm whether the mail module ever advertises IMAP/SMTP on non-default public ports, and if so, prefer that value over the 993/465 default). Do not offer STARTTLS/587 in v1.

- One shared `[global]` section is enough while there is one mail instance and one user domain. Only the `domains` allowlist varies.
- No `allow_insecure`. Plain-text transport is refused.
- Every render is followed by `automx config validate --config ... --domain <each enabled domain>` (run in the container or in CI images). A failing validation aborts the reload and leaves the previous config running; the error is shown in the UI.
- With zero enabled domains the service is stopped and routes are removed.

### 4.4 Traefik routes

For each enabled domain: routes for hosts `autoconfig.<domain>` and `autodiscover.<domain>`, `lets_encrypt` true, `http2https` a configurable default (Thunderbird tries HTTPS then HTTP; some older clients only HTTP; the response contains no secrets; default **true**, revisit if client testing shows a need).

Autodiscover SRV records point at the node FQDN (5.1), so Outlook clients that follow the SRV record connect to `https://<node fqdn>/autodiscover/autodiscover.xml`. That needs a route on the node FQDN restricted to the Autodiscover path prefixes. Create it only when at least one domain is enabled.

**RESOLVED** (2026-09-22, read of `NethServer/ns8-traefik` and `NethServer/ns8-core` `docs/modules/network.md`/`docs/modules/certificates.md`, current `main`): NS8 core does not register a host-based catch-all HTTP route for the bare node FQDN — what it sets up there is a default TLS certificate (self-signed at first, later replaced), not a route. A request to the node FQDN with no matching router simply 404s. So there is nothing for our path-restricted route to collide with; set `host: <node fqdn>`, `path: /autodiscover/autodiscover.xml` (plus the rewritten-capitalized variant per 3.4) on our own route, same as `cluster-admin`'s precedent of a dedicated route on a shared host. Remember the path-prefix Traefik route must also rewrite `/Autodiscover/Autodiscover.xml` to the lowercase path automx actually serves (3.4).

### 4.5 Authorizations and image labels (`build-images.sh`)

- `org.nethserver.authorizations`: `traefik@node:routeadm cluster:accountconsumer dnshelper@cluster:dnswriter mail@any:mailadm`. **Confirmed** (see 3.2): `mailadm` is the only consumer role ns8-mail offers; there is no narrower alternative to verify further. Its grant is broader than needed (also covers `reveal-master-credentials` and relay/BCC control) — call this out in the README and never exercise those actions.
- **RESOLVED, fallback branch applies** (2026-09-22, read of `croessner/automx` `.github/workflows/containers.yml`, `Dockerfile`, `pyproject.toml`, commit `627e7a6`): upstream does publish images, to `ghcr.io/croessner/automx` (Python/Uvicorn) — currently only `:v3.0.0-beta.3` and `:v3.0.0-beta.2` exist (both pre-releases, so no `:latest`/major/minor tags yet) — but **neither installs the `ldap` extra** (`pyproject.toml`'s `ldap = ["python-ldap>=3.4.4,<4"]` optional group is never installed by the Dockerfile, and the runtime base has no `libldap2-dev`/compiler to build it even if we tried to add it at container-start time). Per the anticipated fallback: **`org.nethserver.images` is not usable for automx; build our own image from source in `build-images.sh`.** Pin the exact upstream source ref (currently tag `v3.0.0-beta.3`, matching `pyproject.toml`'s `version = "3.0.0-beta.3"`), install with `pip install '.[ldap]'` plus the native build deps (`libldap2-dev`, `libsasl2-dev`, a compiler — removable in a later build stage), and let Renovate track the pinned upstream ref rather than a floating image tag. Confirmed separately (Containerfile-relevant): inside the container automx listens on port 8000, accepts `--host 0.0.0.0` (the upstream Dockerfile's own `CMD` already does this), runs as UID/GID 10001 (`automx`/`automx`, matching 4.1's assumption), needs a writable `/tmp` (tmpfs) with a read-only root filesystem otherwise, and exposes `/health/live` + `/health/ready` (both deliberately excluded from the OpenAPI schema, per upstream docs).
- Rootless. One TCP port demanded from the node for the loopback listener.
- Minimum NS8 core: **RESOLVED, correction**: dnshelper's own `build-images.sh` actually declares `org.nethserver.min-core=3.20.1`, not 3.22.0 as earlier drafts of this document assumed (checked 2026-09-22). Use `3.20.1` to match. All `set-route` fields this design needs (`host`, `path`, `url`, `lets_encrypt`, `http2https`, `lets_encrypt_check`, `lets_encrypt_cleanup`, `priority`) are present on current `ns8-traefik` `main`; no version-gating information was found suggesting they postdate 3.20.1, but this was not independently checked against a core changelog.

## 5. DNS

### 5.1 Records per enabled domain

| Name | Type | Value |
|---|---|---|
| `autoconfig.<domain>` | CNAME | `<node fqdn>` |
| `autodiscover.<domain>` | CNAME | `<node fqdn>` |
| `_autodiscover._tcp.<domain>` | SRV | `0 0 443 <node fqdn>` |

The PACC TXT record is not created in v1. The node FQDN must itself resolve to A/AAAA records and must not be a CNAME (automx's own `dns check` requires this for a canonical service host). The node FQDN is the default target; expose it as an overridable setting.

automx's `automx dns records --all-domains --format json --service-host <node fqdn>` generates the desired set, and `automx dns check` verifies published records. Both are read-only. Use them as the reference for the records above (and as an early test that the module's plan equals upstream's) rather than reimplementing the record logic. The CNAME owner name equal to the service host is skipped by automx; the same rule applies here.

### 5.2 Status model, per domain and record

`ok` (present and matching) | `missing` | `conflict` (something else exists at that name) | `unmanaged` (no dnshelper zone covers it, cannot be changed automatically) | `not_permitted` (zone managed but no access rule for this module) | `unknown` (lookup failed).

### 5.3 With dnshelper present

1. `has-zone` with the record's host name (for example `autoconfig.mail.example.com`) to find the managed zone, then the record name relative to that zone. A mail domain can be a subdomain of the managed zone.
2. `get-records` for the three names, one call per zone.
3. Compare against 5.1. A CNAME conflicts with any other record at the same name; an SRV conflicts only with a different SRV RRset at that name.
4. Show the plan and any conflicts. The administrator chooses, per domain:
   - **Create**: `append-records` for missing records (after `dry_run`).
   - **Overwrite**: `set-records` for the same name and type where a different value exists, or, for a type conflict (for example an A record where a CNAME is needed), delete the conflicting records with `delete-records` naming name and type, then append the CNAME.
   - **Skip**.
5. Never change anything without an explicit action in the UI. Always run a `dry_run` first and show its `changes`.
6. `not_permitted` is not an error to hide: show that the zone is managed by dnshelper but the module has no rule, and give the rule to add. Creating and overwriting needs a rule for record names `autoconfig`, `autoconfig.*`, `autodiscover`, `autodiscover.*`, `_autodiscover._tcp`, `_autodiscover._tcp.*` with types CNAME and SRV. Deleting conflicting records additionally needs the conflicting types (A, AAAA, TXT, and so on) at the same names, or type `*`. Suggest a "Mail autoconfig" preset in dnshelper's Access page, next to its existing presets; that is a change in the dnshelper repository and is tracked there, not here.
7. Subscribe to `service-dnshelper-changed` to refresh statuses when zones or credentials change.

### 5.4 Without dnshelper (or the zone is not managed)

1. Check by resolving the records from the module (`automx dns check` in the container, or a resolver library available in the module's Python environment; **VERIFY** which is available). The result reflects the public view, which is what clients see.
2. Show the exact records to create (name, type, value, suggested TTL) in copyable form, with a "check again" button.
3. Offer no create/overwrite actions.

### 5.5 Disabling a domain

Disabling removes the domain's routes and its allowlist entry. DNS records are left alone by default. The UI offers "also remove the DNS records" when dnshelper manages the zone, and uses a `delete-records` call with the exact type and value so unrelated records are not touched.

### 5.6 Ordering

Enabling a domain: write state; render and validate config; if DNS for the two hostnames does not resolve yet, mark the domain "waiting for DNS" and do not create routes (or create them and re-check on a timer; decide during implementation, but the user must always be able to see which state a domain is in). When DNS is present, create routes, reload automx, run a probe.

## 6. Actions and events

### 6.1 Actions (`imageroot/actions/<name>/` with `validate-input.json` and `validate-output.json`)

Schemas must accept `null` as well as `{}` for argument-less actions (the admin UI sends no payload; see the dnshelper fix for the same problem).

| Action | Purpose |
|---|---|
| `configure-module` | Settings: service host override (default node FQDN), `http2https` default. Starts the service if at least one domain is enabled. |
| `get-configuration` | Settings plus a summary. |
| `get-domains` | Mail domains from the mail module merged with `state/domains.json`: enabled flag, route status, DNS status per record, orphan flag. |
| `set-domains` | Enable/disable domains; applies routes, renders config, validates, reloads. |
| `check-dns` | Recompute DNS status for one or all domains (dnshelper path or resolver path). |
| `apply-dns` | For one domain: `create`, `overwrite` (with the list of conflicts to delete), each following `dry_run` then execute. dnshelper only. |
| `get-dns-plan` | The records to create, for the manual path. |
| `get-dnshelper-status` | Present or absent, default instance, `allowed` per zone, so the UI can say what is missing. |
| `get-profile-link` | For one domain: the mobileconfig URL template and a ready-to-copy HTML snippet (7.1), built from the current `state/domains.json` and the mobileconfig path/query parameter recorded from automx (VERIFY item 3). No state changes, no automx call. |

### 6.2 Event handlers (`imageroot/events/<event>/`)

- `mail-settings-changed`: re-read domains and mail hostname/ports; re-render, validate, reload; reconcile routes (remove routes for vanished domains).
- `user-domain-changed` and `module-domain-changed`: re-read LDAP parameters; re-render and reload.
- `service-dnshelper-changed`: refresh DNS status cache.

All handlers must be idempotent and safe to run when the mail module, accounts provider or dnshelper is absent.

### 6.3 Errors

Follow NS8 conventions: user-fixable problems (no mail module, no user domain, conflicting DNS, missing dnshelper rule) as `validation-failed` with a specific error code and message; infrastructure failures fail the step with a journal message. Never write credentials into logs or error messages.

## 7. Admin UI (Vue 2, Carbon, `ns8-ui-lib`)

Pages:

- **Status**: service state, number of enabled domains, mail instance and user domain in use, dnshelper present/absent, link to logs.
- **Domains**: table with columns domain, enable toggle, DNS status (a summary tag with a detail drawer), route/certificate status, actions. Row action opens a DNS dialog: records with per-record status, conflicts, `dry_run` preview, and the Create / Overwrite / Skip choices when dnshelper can act; otherwise a copyable list of records and a "check again" button. A banner explains the missing-rule case with the rule to add. A second row action, **Get profile link**, opens the dialog described in 7.1.
- **Settings**: service host override, `http2https` default.
- **About**: standard.

The domains table must state clearly, for domains with no dnshelper coverage, that DNS is manual. English is the source language in `ui/public/i18n/en/translation.json`.

### 7.1 Profile link and self-service snippet, for the administrator's own use

The automx endpoints are unauthenticated by design (a client supplies only an email address), so there is no user-facing self-service page inside this module and no plan to add one — see 3.1 in the NS8 docs research: the closest built-in candidate, `/users-admin/<domain>/` from `ns8-user-manager`, only shows a static, non-linked "services" text list configured by the accounts-provider module, not an extension point this module can register into (that's tracked as a possible later, cross-module change; see section 12). Instead, this module gives the *administrator* two things per enabled domain, so they can put a download option wherever their users already are (an intranet page, the organization's wiki, a welcome email):

**RESOLVED, and it changes this section** (2026-09-22, read of `croessner/automx` `src/automx/app.py`, commit `627e7a6`): `GET /mobileconfig` is not the profile — it returns automx's own small HTML download form (no JS/CSS required to function; the JS/CSS are cosmetic theme/language toggles). The actual profile comes from `POST /mobileconfig` (form-urlencoded body: `emailaddress` required, optional `cn`, hidden `_mobileconfig=true`; a supplied `password` field is rejected). There is no GET-with-query-string way to download the profile directly — VERIFY item 3's assumed `?emailaddress=%s` URL does not work.

This means automx already ships the self-service form section 7.1 set out to build. Two options, both cheap:

1. **The direct URL** (still offered): `https://autoconfig.<domain>/mobileconfig` — automx's *own* form, unmodified. No snippet needed at all; this is the simplest v1 default.
2. **A copyable HTML snippet**, for an administrator who wants the form embedded inline on their own page (matching branding, or skipping the extra click to automx's page) rather than linking out to it. It must `POST`, not `GET`, and use automx's exact field names.

Mock-up, one snippet per enabled domain (styling deliberately minimal; the admin's own page CSS will typically override it):

```html
<!-- Paste this where you want a "Download email settings" form.
     Generated by ns8-automx for domain: example.com -->
<form action="https://autoconfig.example.com/mobileconfig" method="post"
      style="max-width:22rem;font:14px sans-serif">
  <input type="hidden" name="_mobileconfig" value="true">
  <label for="automx-email">Your email address</label><br>
  <input id="automx-email" name="emailaddress" type="email"
         placeholder="you@example.com" required
         pattern="[^@\s]+@example\.com"
         title="Must be an example.com address"
         style="width:100%;box-sizing:border-box;margin:.4em 0;padding:.4em">
  <button type="submit">Download mail profile</button>
</form>
```

Notes on the mock-up, to carry into implementation:

- The `pattern` attribute is a client-side hint only (it stops the obviously wrong domain, not a security boundary); automx itself validates the address and simply won't find a match for an address outside its configured domains. The generated snippet fills in the real domain from `state/domains.json`.
- A plain `POST` form still needs no fetch call, no CORS concern, and no data other than the address the user themselves typed and its submission leaves their browser as a normal (if not literally GET-bookmarkable) form submission.
- If more than one domain is enabled, offer both a per-domain snippet (as above, simplest) and, as a second copyable option, one combined snippet whose small inline script reads the typed address, extracts its domain, and sets the form's `action` to the matching enabled domain's URL before submitting, rejecting anything else with an inline message. Build the combined version only if the per-domain one turns out to be too limiting in practice; start with per-domain snippets (or just the bare URL) in v1.
- The snippet's `action` host is one of this module's own Traefik routes (`autoconfig.<domain>` from 4.4), so it needs no new route, no new action beyond generating the text, and no change to automx's own exposure (8): it's a convenience wrapper around a URL that is already public, not a new capability.

## 8. Security

- Container: non-root as shipped (UID 10001), read-only root filesystem, config mounted read-only, no extra capabilities. The published port is bound to the node's loopback only; the only exposure is through Traefik.
- Do not enable proxy-header trust in automx beyond what the packaged `serve` default allows. Do not forward client-supplied base URLs.
- The LDAP bind credentials come from ldapproxy for the module's own bound domain; treat them as secrets (0600 file, not in Redis, not in backups, not in logs). **RESOLVED** (see 3.3): the credentials are consumed by our own lookup script, not automx's native LDAP backend (which is not used — see 3.3's `script`-backend decision); connect to ldapproxy with `ldap://` and no TLS, matching automx's own `usetls = no` compatibility finding.
- Autoconfig responses contain server names and, via LDAP, a display name for an address the requester supplied. That is address-to-name disclosure by design of the protocol. Decide whether to restrict display names to authenticated lookups (they cannot be) or omit display names by default (**decision needed**: default on, with a setting to turn off).
- Rate limiting belongs at the ingress (Traefik); automx removed its own failure counter. Note this in the README and consider a default Traefik middleware if the platform allows.
- The profile-link snippet (7.1) is a thin wrapper around the already-public mobileconfig URL: it adds no authentication and should not be described to administrators as adding any. Its only purpose is convenience (a form instead of a bare URL to distribute).

## 9. Testing

Unit tests and CI catch regressions in the renderer and config validity, but they cannot exercise Traefik, ldapproxy, dnshelper or a real accounts provider — those only exist on an actual NS8 node. **A real-node integration pass is therefore mandatory before this module is considered done, not an optional nice-to-have**, modeled on dnshelper's own `tests/integration/` (a re-runnable script against a real node, not a one-off manual check).

### 9.1 Unit tests and CI (no node needed)

- Unit tests (Python): renderer golden files for OpenLDAP and AD, zero/one/many domains, quoting of odd input; DNS comparison logic (5.2's status model); state merge (mail domains + stored flags, orphans).
- CI: build image, run `automx config validate` and `automx render autoconfig|autodiscover|mobileconfig` against rendered configs with a synthetic address.
- Robot smoke test (`tests/`, run by `test-module.sh` in CI): install, `configure-module`, enable a domain, check service health, uninstall. This runs on a throwaway CI node and cannot cover LDAP or dnshelper, since neither is installed there; it only proves the module starts and stops cleanly.

### 9.2 Real-node integration test (required)

Build a `tests/integration/` suite that installs this module on a real NS8 node alongside the mail module and an accounts provider, and drives it through `api-cli`/actions the way `tests/integration/consumer/` does for dnshelper. It must be re-runnable (clean up after itself, or refuse to run next to an existing instance, as dnshelper's does) and cover the full matrix below, not just one path through it — the goal is to catch the interactions unit tests can't see: real Redis service-discovery keys, real event payloads, real Traefik/Let's-Encrypt behavior, and the two accounts-provider schemas actually returning different attribute names.

**Accounts provider (run the full matrix once per provider):**

| Provider | Schema | What it proves |
|---|---|---|
| OpenLDAP | `rfc2307` | `uid`/`mail`/`cn` mapping (3.3) resolves a real bind, login and display name come back correctly |
| Samba AD | `ad` | `sAMAccountName`/`mail`/`displayName` mapping resolves against a real AD-schema directory; catches attribute-name mistakes OpenLDAP testing alone would miss |

For each provider, test: a user whose primary address matches the login (`dan@domain`), a user with a free-form alias (expected: static fallback per 3.3, not a wrong login), and the "no LDAP entry matches" and "LDAP unreachable" fallback paths (**VERIFY** item 2 — confirm actual automx behavior here, not just the desired one).

**dnshelper (run the enable/DNS flow with and without it):** use RFC 2136 against a local BIND instance for the dnshelper zone in this suite (as dnshelper's own `helper/testdata/bind` does) — it's sufficient for automated testing since it needs no external account and dnshelper's live-provider behavior (Cloudflare, GoDaddy, Hetzner, name.com, Core-Networks) is already covered by dnshelper's own test suite against real domains and credentials; this module's tests only need to prove that *this module* drives the dnshelper consumer API correctly, not that dnshelper itself talks to a given provider correctly.

| Scenario | What it proves |
|---|---|
| dnshelper installed, zone managed, no access rule yet | `not_permitted` path (5.3.6): the module detects the missing rule and surfaces the exact rule to add, rather than failing opaquely |
| dnshelper installed, zone managed, rule granted, no existing records | Create path: `dry_run` preview, then `append-records`, then a passing DNS status |
| dnshelper installed, zone managed, rule granted, conflicting record already present (e.g. an existing A record at `autoconfig.<domain>`) | Conflict detection (5.2) and both the overwrite path (`delete-records` + `append-records`) and the skip path |
| dnshelper installed, but the domain's zone is *not* one dnshelper manages | `unmanaged` status; module falls back to the manual/check-only flow for that domain even though dnshelper is present |
| dnshelper not installed at all | `agent.list_service_providers` returns empty; the module runs the resolver-based check (5.4) end to end and shows correct copyable records; no create/overwrite actions are offered |
| dnshelper installed after the module was already configured (order-of-install) | `service-dnshelper-changed` (or the module noticing it on next check) picks up the newly available zone without requiring the domain to be disabled and re-enabled |

**Combined with the above:** at least one full run of "OpenLDAP + dnshelper present" and one full run of "AD + dnshelper absent" (or the inverse pairing), so the two axes aren't only ever tested independently.

**Also cover on the real node:** Traefik route and Let's Encrypt certificate creation for `autoconfig.<domain>`/`autodiscover.<domain>` (4.4), the node-FQDN Autodiscover path route, disabling a domain (route and, optionally, DNS record removal per 5.5), backup and restore (4.2), and module removal.

### 9.3 Client tests (manual)

Thunderbird (Autoconfig), Outlook (Autodiscover via CNAME and via SRV), Apple Mail (mobileconfig), using a user's primary address and an alias, against the real node set up in 9.2 (not a mocked config) so the actual served XML/plist is what's being tested.

## 10. Decisions log

| # | Decision |
|---|---|
| 1 | Use croessner/automx 3.x (beta), pinned; not automx2. |
| 2 | One mail instance and one shared user domain in v1; data model keyed by mail instance so more can be added. |
| 3 | Domains default disabled; the administrator opts in per domain. |
| 4 | Traefik routes and Let's Encrypt certificates are created for `autoconfig.<domain>` and `autodiscover.<domain>` by this module. |
| 5 | LDAP lookup is in v1, for login name and display name, both schemas. Login is the bare username; the address itself is a valid login only when it equals `user@domain`. Mail aliases are not resolved in v1. **Amended 2026-09-22**: implemented via automx's `script` backend with our own lookup script, not the native `backend = ldap` (which can't express the login-or-mail rule and has no fallback-on-miss — see 3.3). |
| 6 | dnshelper is optional. When present and covering the zone, the module offers create/overwrite/skip for CNAME and SRV, after a dry run and explicit confirmation. When absent, it checks by resolving and shows the records to create. |
| 7 | CNAME and SRV target is the node FQDN (overridable). No PACC TXT in v1. |
| 8 | Protocols in v1: Autoconfig, Autodiscover, mobileconfig (unsigned). |
| 9 | Image: **amended 2026-09-22** — upstream's `ghcr.io/croessner/automx` never installs the `ldap` extra, so it can't be used as-is; build from source in `build-images.sh` from a pinned upstream tag (currently `v3.0.0-beta.3`), Renovate tracks the pinned source ref. |
| 10 | Minimum NS8 core **3.20.1** (corrected 2026-09-22 — matches dnshelper's actual `build-images.sh` declaration, not the earlier-assumed 3.22.0). |
| 11 | Client-facing IMAP and SMTP use implicit TLS on the standard secure ports, IMAPS 993 and SMTPS 465, not STARTTLS/587, unless the mail module explicitly reports different public ports. |

## 11. VERIFY list (resolve during implementation)

1. **RESOLVED** (2026-09-22, read of `NethServer/ns8-mail`). Mail module: `get-configuration` returns the public hostname (`hostname`, Postfix `myhostname`); `list-domains` output schema is `domain, addusers, addgroups, addaliases, catchall, bccaddr, description` per domain (no ports, no per-domain user_domain); `mailadm` is the only consumer role and it is broader than needed (also grants `reveal-master-credentials` and relay/BCC control) — there is no narrower option upstream. Ports are never advertised anywhere in ns8-mail; IMAPS 993 / SMTPS 465 (decisions log #11) are hardcoded upstream and not overridable. See 3.2 and 4.5 for detail.
2. **RESOLVED, changes the design** (2026-09-22, read of `croessner/automx` source, commit `627e7a6`/`v3.0.0-beta.3`). No local-part placeholder exists inside the native `backend = ldap`'s `filter` (only `%s`, the full address); the two-step login-or-mail lookup rule (3.3) cannot be expressed there. On no-match or connection failure the native backend hard-fails the request (`ConfigurationError` → HTTP 400 for Autoconfig/Mobileconfig, an error XML for Autodiscover) with no fallback to static defaults. `reqcert=demand` is fixed but TLS-only, so `usetls = no` + `ldap://` against the plaintext loopback ldapproxy hop is fine. **Decision made**: use automx's `script` backend with our own lookup script instead of `backend = ldap` — see 3.3.
3. **RESOLVED** (same source). Autoconfig: `GET /mail/config-v1.1.xml` and `GET /.well-known/autoconfig/mail/config-v1.1.xml`. Autodiscover: only `POST /autodiscover/autodiscover.xml` — automx has no capitalized-path route; Outlook's `/Autodiscover/Autodiscover.xml` needs a Traefik-side rewrite to the lowercase path, not a second pass-through route. Mobileconfig: `GET /mobileconfig` returns automx's own HTML download form (no JS required); the profile itself is `POST /mobileconfig` (form-urlencoded `emailaddress`, optional `cn`), not a GET query string — see 7.1, which now points administrators at automx's own form by default instead of a GET-based snippet.
4. **RESOLVED, fallback branch applies** (same source). Upstream publishes `ghcr.io/croessner/automx`, currently only pre-release tags (`v3.0.0-beta.3`, `v3.0.0-beta.2`), no `ldap` extra installed in either. Build our own image from the pinned upstream source ref with `pip install '.[ldap]'` — see 4.5.
5. **RESOLVED** (2026-09-22, read of `NethServer/ns8-traefik`, current `main`). `set-route` fields: `instance` (required, idempotency key), `url`, `host`, `path` (path-prefix filter — confirms per-host, per-path routing is supported, contradicting nothing in the design), `priority`, `lets_encrypt(_check|_cleanup)`, `http2https`, plus fields we don't need (`strip_prefix`, `slash_redirect`, `skip_cert_verify`, `ip_allowlist`, `headers`, `forward_auth`). `delete-route`: `instance`, optional `lets_encrypt_cleanup` — though in practice not needed for our own cleanup, since ns8-traefik's `module-removed` handler already deletes every route whose instance name contains the module's `module_id`. Node-FQDN coexistence and Let's-Encrypt-when-DNS-isn't-ready are resolved in 3.4/4.4 — no retry/backoff exists at the NS8 level; use `lets_encrypt_check: true` with `error_passthrough=False` to get a synchronous, handleable failure instead of an aborted action.
6. Default `http2https` for the autoconfig hosts, after real-client tests. (Still open — needs manual client testing per 9.3, not resolvable by source reading.)
7. Which resolver tooling is available in the module's Python environment for the no-dnshelper DNS check, or whether `automx dns check` in the container is used. (Still open.)
8. Display-name default (see section 8). (Still open — a product decision, not a fact to look up.)
9. **RESOLVED**: NS8 core minimum version 3.20.1 (corrected from the earlier-assumed 3.22.0 — see decisions log #10 and 4.5).
10. **RESOLVED** (2026-09-22, read of `croessner/automx` `Dockerfile`/`compose.yaml` and `NethServer/ns8-core` `docs/modules/network.md`). Networking: NS8's documented pattern is exactly what 4.1 assumed — the isolated-namespace option publishes on `127.0.0.1:${TCP_PORT}` on the node, Traefik reaches it there; `--network=host` is the documented faster alternative with no port-proxy. automx listens on port 8000 inside the container, its own `Dockerfile` `CMD` already passes `--host 0.0.0.0 --port 8000` (so `--host 0.0.0.0` is accepted and is the documented container invocation), and the published image runs as UID/GID 10001 (`automx`/`automx`, matching 4.1's file-ownership assumption) with a writable `/tmp` tmpfs over an otherwise read-only root filesystem. Since we're building our own image from source (item 4/VERIFY 9), carry these same values (port 8000, `--host 0.0.0.0`, UID 10001, tmpfs `/tmp`) into our Containerfile rather than upstream's unusable published image.

## 12. Later phases

- PACC TXT record and JSON, once the drafts stabilize (needs the cache-safe TXT rollover described in automx's migration guide).
- Alias resolution: generate a map from the mail module's addresses at render time and serve it through automx's bounded `script` backend, so an alias resolves to its owner's login.
- Several mail instances and user domains (per-domain sections in `automx.conf`).
- Mobileconfig signing with a configured certificate.
- Autodiscover v2, OAuth public-client metadata.
- True self-service integration into `/users-admin/<domain>/` (ns8-user-manager): today that page only shows a static, non-linked "services" text list configured by the accounts-provider module (samba/openldap), so putting a real download link there needs cross-module work — either that page's "services" entries becoming linkable, or a new registration mechanism other modules can feed. That's a feature request against `ns8-user-manager` (and possibly `ns8-samba`/`ns8-openldap`), not something achievable from within `ns8-automx` alone. Section 7.1's copyable snippet is the v1 substitute: it gives the administrator the same end-user outcome without depending on another module's release.
# Integration test on a real NS8 node

`test_node.py` installs automx on a real NS8 node and drives it through its actions the way
`tests/integration/consumer/` does for dnshelper (DESIGN.md 9.2: unit tests and the Robot smoke
test (`tests/`) can't see real Redis service-discovery keys, real event payloads, real
Traefik/Let's-Encrypt behavior, or an accounts provider's actual attribute names -- this is the
pass that does).

Unlike `ns8-dnshelper`'s own integration test, this one does **not** set up its own mail domain or
accounts provider from scratch: DESIGN.md 9.2's matrix needs both the `rfc2307` (OpenLDAP) and `ad`
(Samba AD) schemas exercised against a real bind, which is its own significant setup outside
automx's own scope. Point this test at a node that already has:

- a configured mail module instance, with at least one mail domain and a bound user domain;
- in that user domain, a user whose primary address (`<login>@<mail domain>`) is known, and
  (recommended, to cover DESIGN.md 3.3's alias case) a second user with a free-form mail alias
  that is *not* their login;
- optionally, `ns8-dnshelper` installed and covering the mail domain's DNS zone (RFC 2136 against a
  local BIND, as dnshelper's own `helper/testdata/bind` sets up, is sufficient and needs no external
  account -- see dnshelper's README). Run the test once with dnshelper present and once without, to
  cover both of DESIGN.md 5.3/5.4's paths; with it present, also add (and separately, deliberately
  *not* add) the access rule described in DESIGN.md 5.3.6 to cover the `not_permitted` case.

The test refuses to start if an `automx*` instance already exists (it only removes what it
installed itself). It installs the **published** image, `ghcr.io/danb35/automx:latest` by default
(override with `AUTOMX_IMAGE`, for example a branch image `ghcr.io/danb35/automx:<branch>` that CI
published): a fresh `add-module` cannot use an image built on the node, because the module's
rootless podman storage is separate from root's and `localhost/` is not a registry it can pull from.

## Prerequisites

- An NS8 node you can `ssh root@` with a key, and outbound internet access to ghcr.io.
- The mail module, accounts provider, and (optionally) dnshelper already configured as above.
- `buildah` on the node only for the by-hand flow at the bottom (`update-on-node.sh`).

## Nodes without inbound internet access

Route creation needs `autoconfig.<domain>` to resolve to the node and Let's Encrypt to reach it
(DESIGN.md 5.6). On a node that is not reachable from outside, or whose mail domain has no public
DNS pointing at it, the module correctly holds the routes back (`waiting_for_dns`). The test
detects that and asserts the gate instead: no route exists, and `get-domains` says why. Route and
certificate creation itself is only exercised on a node that can satisfy both.

## Running

```bash
NS8_NODE=192.168.1.20 NS8_SSH_KEY=~/.ssh/id_ed25519 \
MAIL_MODULE_ID=mail1 MAIL_DOMAIN=example.test \
TEST_USER_LOGIN=dan TEST_USER_MAIL=dan@example.test \
TEST_ALIAS_MAIL=dan.brown@example.test \
    python3 -m unittest tests/integration/test_node.py -v
```

`NS8_NODE`, `MAIL_MODULE_ID` and `MAIL_DOMAIN` are required (the test is skipped without them).
`TEST_USER_LOGIN`/`TEST_USER_MAIL` (a real user's login and primary address in the mail domain's
user domain) are required to test the LDAP lookup path meaningfully; without them that part is
skipped and only the static/fallback behavior is checked. `TEST_ALIAS_MAIL` is optional and covers
DESIGN.md 3.3's "an alias is not a valid login, falls back" case. `DNSHELPER_MODULE_ID` (optional)
points at an already-installed dnshelper instance covering `MAIL_DOMAIN`'s zone, to exercise the
dnshelper-present DNS paths; without it, only the manual/resolver path (5.4) is checked.

The Robot suite in `tests/` is the node's smoke test (`test-module.sh`); run it with the directory,
not the file, so that `__init__.robot` opens the SSH connection:

```bash
robot -v NODE_ADDR:<node> -v IMAGE_URL:localhost/automx:test -v SSH_KEYFILE:~/.ssh/id_ed25519 tests/
```

after `tests/integration/build-on-node.sh <node>`.

## Working with an installed instance

To try local, unpublished code by hand, install the published image first, then update the
instance **in place** (keeping `state/domains.json` and `state/settings.json`) to a build of your
working tree under a new tag:

```bash
ssh root@<node> add-module ghcr.io/danb35/automx:latest 1
tests/integration/update-on-node.sh <node> automx1 dev1
```

Update again with another new tag after each change:

```bash
tests/integration/update-on-node.sh <node> automx1 dev2
```

The integration test itself must run on a node without an automx instance (see above).

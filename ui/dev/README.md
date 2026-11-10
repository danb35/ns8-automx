# UI harness

The automx UI only runs inside the NS8 shell (it reads `window.parent.core`), which makes it
awkward to look at. This harness fakes the shell so the built UI can be exercised in a browser.
It is adapted from [ns8-dnshelper's](https://github.com/danb35/ns8-dnshelper/tree/master/ui/dev).

- `harness.html` is the parent page: it provides `window.core` (an event emitter, `apiUrl`,
  `$t`) and relays task results to the app, the way the shell does over its websocket.
- `server.py` is a mock NS8 API. automx's actions need a live node (mail module, ldapproxy,
  Traefik, dnshelper), so their outputs are canned: a mail server `mail1` with the domains
  `example.com` (DNS through dnshelper), `example.org` (manual DNS, with its own settings) and
  `example.net` (disabled, dnshelper without an access rule), plus Nextcloud, SOGo and WebTop.
  Settings and per-domain overrides go through the module's real `automx.state` code, and the DNS
  records through `automx.dns.expected_records()`. The canned outputs follow each action's
  `validate-output.json`; check them again when an output schema changes.

```bash
cd ui && yarn build                    # or copy a node's /var/lib/nethserver/cluster/ui/apps/<automx id>/ to ui/dist
CORE_CSS=/path/to/core.css python3 dev/server.py
```

`CORE_CSS` is the NS8 core UI's stylesheet: the concatenation of its `css/app~*.css` files, for
example `ssh root@<node> 'cat /var/lib/nethserver/cluster/ui/css/app~*.css' > core.css`. Without
it the app renders without the shell's Carbon styles.

## Screenshots

`screenshots.js` drives the harness in a headless browser and takes the pictures used in
[docs/USER-GUIDE.md](../../docs/USER-GUIDE.md), so that they can be redone when the UI changes.
Pages are taken 800 pixels wide; the large dialogs (DNS status, profile link) at 1056, where they
show as a window over the page.

```bash
# in one terminal: the harness, with the shell's stylesheet
CORE_CSS=/path/to/core.css python3 ui/dev/server.py

# in another: the browser, in Docker (Docker Desktop reaches the host as host.docker.internal)
mkdir -p /tmp/shots
docker run --rm -v "$PWD/ui/dev:/work" -v /tmp/shots:/out -w /work \
    mcr.microsoft.com/playwright:v1.49.1-jammy \
    bash -c "npm init -y >/dev/null && npm i playwright-core@1.49.1 >/dev/null && OUT=/out node screenshots.js"
```

Set `LOCALE` (for example `-e LOCALE=de-DE` on the `docker run`) to take the pictures in another
language, to check that translated labels fit; the script finds pages by their place in the menu,
not their name.

Start from a fresh harness (it keeps changes made through the UI until it is stopped), then copy the
pictures into `docs/images/`. `dnshelper-access.png` is dnshelper's own page and is not taken here.

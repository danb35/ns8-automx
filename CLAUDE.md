Read @DESIGN.md before doing anything; items marked VERIFY must be checked against the NS8 docs or a live node, not assumed.

@AGENTS.md

## dnshelper (DNS records)

This module changes DNS records by calling the `dnshelper` module, which lives in its own
repository: https://github.com/danb35/ns8-dnshelper (checked out locally at
`/Users/dan/Documents/GitHub/ns8-dnshelper`). Before writing or changing any code that calls it,
read the README section "Using dnshelper from another module" there, and the JSON schemas in
`imageroot/actions/<action>/validate-*.json`. A working example consumer is
`tests/integration/consumer/`. Do not work from memory of the API.

- Declare `org.nethserver.authorizations=dnshelper@cluster:dnswriter` (or `dnsreader`) in
  `build-images.sh`.
- Find it with `agent.list_service_providers(rdb, 'dnshelper')`; handle it being absent.
- Modules are denied everything until an administrator adds an access rule for them in dnshelper's
  Access page. Our docs and error handling must say which rule to add (module, zones, record names
  and types). `not_permitted` means a missing rule, not a bug.
- Use `dry_run` to preview a change. Rotate a value with `set-records` in merge mode, not rrset mode.
- Provider limits (TTL floors, refused TXT characters, slow APIs) are in dnshelper's README under
  "Providers".
- If dnshelper needs a change, make it in the dnshelper repo, as its own branch and PR; do not work
  around it here.
- Do not modify or remove the dnshelper instance on the test node (it holds real zones and
  credentials).
  

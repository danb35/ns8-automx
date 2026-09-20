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
  

## GitHub Actions setup

This repo came from the ns8-kickstart template, whose workflows do not work unmodified. These are
the fixes that dnshelper needed (https://github.com/danb35/ns8-dnshelper); do them before
expecting green runs, and check the Actions tab after the first push.

- **Rename every `kickstart` placeholder.** `reponame="kickstart"` in `build-images.sh`,
  `images: "kickstart"` in `.github/workflows/clean-registry.yml`, and `image_name: kickstart` in
  `.github/workflows/test-module-qemu.yml` (it must match `reponame`). Also the robot test file and
  its texts in `tests/`, `ui/public/metadata.json` and the i18n files. A module name must not end
  in a digit.
- **Keep the repo public.** While dnshelper was private its first "Publish images" run failed at
  checkout with "Repository not found". `publish-images.yml` skips the very first run
  (`if: github.run_number > 1`); that is normal. After the first publish, check that the ghcr
  package can be pulled anonymously; if not, set its visibility to public in the package settings.
- **Add `permissions: contents: write` to `build-apidoc.yml` and `clean-apidoc.yml`** (at the top
  level, beside `on:`). A reusable workflow cannot exceed its caller's permissions and this
  repository's default token is read-only, so without it the run fails with `startup_failure`.
  Do not raise the repository-wide default instead. Adding `workflow_dispatch:` to
  `build-apidoc.yml` allows running it by hand.
- **Replace `.github/workflows/clean-registry.yml`.** The template's version calls a shared action
  that needs an `IMAGES_CLEANUP_TOKEN` secret that does not exist (it hangs on a browser login until
  it times out) and looks the image up under `basename(ref)`, although the publish workflow tags an
  image with the ref where every `/` became `-`, so branches with a slash never match while the run
  still reports success. Copy dnshelper's version
  (https://github.com/danb35/ns8-dnshelper/blob/master/.github/workflows/clean-registry.yml): it
  works out the tag the same way as the publish workflow, deletes only an image tagged exactly that,
  refuses `master`, `main` and `latest`, uses the built-in `github.token` (`packages: write`), and
  can be run by hand with a `tag` input. Change its `IMAGES:` to this module's image name. Drop
  `environment: Registry`: it only creates a failed "Registry" deployment entry per run.
- **Deleting a branch while its image publish is still running** leaves the image behind (the
  clean-up ran first). Run it by hand: `gh workflow run clean-registry.yml -f tag=<branch with / as ->`.

How the tests run: `test-module-qemu.yml` starts after "Publish images" succeeds (`workflow_run`),
boots throwaway NS8 nodes (Rocky 9 and Debian 13) and runs `tests/*.robot` against the image just
published as `ghcr.io/danb35/<module>:<branch>`. It needs `permissions: contents: read,
pull-requests: write` in the caller (the template has it). `tests/__init__.robot` opens the SSH
connection. Robot tests must use fake credentials only; nothing in CI may talk to a real service.
It has failed for reasons unrelated to the code (SSH connection refused right after the VM starts;
NS8's own cluster setup failing to pull its default `metrics` module): re-run before suspecting the
module, and read the failing step with `gh run view --job <id> --log`.

Image tags: every pushed branch or tag publishes `ghcr.io/danb35/<module>:<ref>` with `/` replaced by
`-`; `master` also updates `latest`. Release tags are plain semver without a `v` (for example
`0.1.0`), annotated, on a commit whose checks all passed.

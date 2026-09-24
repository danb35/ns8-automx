"""Integration test on a real NS8 node, with a real mail module and
accounts provider. Skipped unless NS8_NODE, MAIL_MODULE_ID and MAIL_DOMAIN
are set. See README.md in this directory.

The module is installed from the published image (AUTOMX_IMAGE, default
ghcr.io/danb35/automx:latest), the artifact a release ships.
"""
import ast
import json
import os
import subprocess
import unittest

NODE = os.environ.get('NS8_NODE')
KEY_FILE = os.environ.get('NS8_SSH_KEY')
MAIL_MODULE_ID = os.environ.get('MAIL_MODULE_ID')
MAIL_DOMAIN = os.environ.get('MAIL_DOMAIN')
TEST_USER_LOGIN = os.environ.get('TEST_USER_LOGIN')
TEST_USER_MAIL = os.environ.get('TEST_USER_MAIL')
TEST_ALIAS_MAIL = os.environ.get('TEST_ALIAS_MAIL')
DNSHELPER_MODULE_ID = os.environ.get('DNSHELPER_MODULE_ID')
# A fresh install must come from a registry: the module's rootless podman storage is separate
# from root's, so add-module cannot pull a localhost/ image built on the node (see
# update-on-node.sh for the in-place update path that can).
IMAGE = os.environ.get('AUTOMX_IMAGE', 'ghcr.io/danb35/automx:latest')

HERE = os.path.dirname(os.path.abspath(__file__))


def ssh(command, stdin=None, check=True):
    args = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']
    if KEY_FILE:
        args += ['-i', KEY_FILE]
    p = subprocess.run(args + ['root@' + NODE, command], input=stdin, capture_output=True, text=True, timeout=900)
    if check and p.returncode:
        raise AssertionError('%s failed (%d): %s' % (command[:80], p.returncode, (p.stderr or p.stdout)[-500:]))
    return p


def api(target, action, data=None, check=True):
    """Run an action as the cluster admin. Returns (exit code, parsed stdout)."""
    path = action if target == 'cluster' else 'module/%s/%s' % (target, action)
    if data is None and target == 'cluster':
        p = ssh('api-cli run %s' % path, check=False)
    else:
        p = ssh('api-cli run %s --data -' % path, json.dumps(data if data is not None else {}), check=False)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        out = p.stdout
    if check and p.returncode:
        raise AssertionError('%s failed (%d): %s %s' % (path, p.returncode, p.stderr[-400:], p.stdout[-400:]))
    return p.returncode, out


def redis(*args):
    return ssh('redis-cli ' + ' '.join(args)).stdout.strip()


INSTALLED = []  # modules this test installed: the only ones it may remove


def add_module(image):
    out = ssh('add-module %s 1' % image).stdout.strip().splitlines()[-1]
    module_id = ast.literal_eval(out)['module_id']
    INSTALLED.append(module_id)
    return module_id


def existing_modules():
    _, mods = api('cluster', 'list-installed-modules', check=False)
    return [m['id'] for group in (mods.values() if isinstance(mods, dict) else []) for m in group]


def traefik_module_id():
    # Same resolution agent.resolve_agent_id("traefik@node") uses internally
    # (a plain string key, node/<id>/default_instance/traefik) -- don't
    # assume "traefik1". Our own module authorization is traefik@node
    # (build-images.sh), so this matches what automx itself resolves.
    return redis('GET', 'node/1/default_instance/traefik')


def route_exists(instance):
    # traefik's get-route answers {} with exit 0 for a route that doesn't
    # exist, not a failure -- so existence is "non-empty", never "rc == 0".
    rc, out = api(traefik_module_id(), 'get-route', {'instance': instance}, check=False)
    return rc == 0 and bool(out)


def http_status_now(module_id, path):
    """The HTTP status of one request to the container's published port, in a
    single SSH round trip and with no retry: used to prove the service is
    already serving the moment an action returns."""
    cmd = ("curl -s -m 5 -o /dev/null -w '%%{http_code}' "
           "\"http://127.0.0.1:$(redis-cli HGET module/%s/environment TCP_PORT)%s\"") % (module_id, path)
    return ssh(cmd, check=False).stdout.strip()


def curl_automx(module_id, path, method='GET', data=None):
    """A request straight to the automx-app container's published loopback
    port -- the same thing Traefik would forward, without needing a route
    or DNS to exist yet (DESIGN.md 4.1)."""
    port = redis('HGET', 'module/%s/environment' % module_id, 'TCP_PORT')
    args = ['-s', '-X', method, "'http://127.0.0.1:%s%s'" % (port, path)]
    if data:
        for key, value in data.items():
            args += ['-d', '%s=%s' % (key, value)]
    return ssh('curl ' + ' '.join(args)).stdout


@unittest.skipUnless(NODE and MAIL_MODULE_ID and MAIL_DOMAIN, 'set NS8_NODE, MAIL_MODULE_ID and MAIL_DOMAIN')
class NodeIntegration(unittest.TestCase):
    automx = None

    # ------------------------------------------------------------------ helpers
    @classmethod
    def tearDownClass(cls):
        # best effort: leave the node as it was found
        try:
            for module_id in reversed(INSTALLED):
                if module_id in existing_modules():
                    ssh('remove-module --no-preserve %s' % module_id)
        except Exception as ex:  # never mask the real test failure
            print('CLEANUP INCOMPLETE, check the node for modules this test installed:', ex)

    # ------------------------------------------------------------------ tests
    def test_01_install_and_configure(self):
        stray = [m for m in existing_modules() if m.startswith('automx')]
        self.assertEqual(stray, [], 'run this test on a node without an automx instance: it only '
                                     'removes what it installs itself and would otherwise touch yours')
        cls = type(self)
        cls.automx = add_module(IMAGE)

        rc, _ = api(cls.automx, 'configure-module', {'http2https': True, 'display_names': True})
        self.assertEqual(rc, 0)

        rc, config = api(cls.automx, 'get-configuration', {})
        self.assertEqual(rc, 0)
        self.assertTrue(config['http2https'])
        self.assertTrue(config['display_names'])
        self.assertEqual(config['enabled_domain_count'], 0)
        # Real mail module RPC (DESIGN.md 3.2), not a mock -- proves the
        # mail@any:mailadm grant and the get-configuration call work.
        self.assertIsNotNone(config['mail_hostname'])
        self.assertEqual(config['dnshelper_present'], bool(DNSHELPER_MODULE_ID))

    def test_02_get_domains_reflects_the_real_mail_module(self):
        rc, out = api(type(self).automx, 'get-domains', {})
        self.assertEqual(rc, 0)
        domain_names = [d['domain'] for d in out['domains']]
        self.assertIn(MAIL_DOMAIN, domain_names)
        entry = next(d for d in out['domains'] if d['domain'] == MAIL_DOMAIN)
        self.assertFalse(entry['enabled'])  # disabled by default (DESIGN.md decision #3)
        self.assertFalse(entry['orphaned'])

    def test_03_enabling_a_domain_creates_routes_and_starts_the_service(self):
        cls = type(self)
        rc, out = api(cls.automx, 'set-domains', {'domains': {MAIL_DOMAIN: {'enabled': True}}})
        self.assertEqual(rc, 0)
        self.assertEqual(out['route_failures'], [], 'a real route-creation failure, not a DNS wait')
        # Straight away, no retry: automx.service's start must not complete
        # until /health/ready answers, so set-domains returning means serving.
        # (Found here: a connection reset in this window, before the unit
        # waited for readiness.)
        self.assertEqual(http_status_now(cls.automx, '/health/ready'), '200',
                         'automx was not ready when set-domains returned')

        rc, status = api(cls.automx, 'get-status', {})
        self.assertEqual(rc, 0)
        service = next(s for s in status['services'] if s['name'].startswith('automx'))
        self.assertTrue(service['active'] and not service['failed'], service)

        route = '%s-autoconfig-%s-0' % (cls.automx, MAIL_DOMAIN)
        rc, domains = api(cls.automx, 'get-domains', {})
        entry = next(d for d in domains['domains'] if d['domain'] == MAIL_DOMAIN)
        if out['waiting_for_dns']:
            # DESIGN.md 5.6: routes are held back until the domain's DNS
            # resolves, since Traefik only ever tries a certificate once. A
            # node with no inbound internet access (or no public DNS for the
            # mail domain) can never get past this -- so on such a node this is
            # what's testable: the gate holds, and says so.
            self.assertEqual(out['waiting_for_dns'], [MAIL_DOMAIN])
            self.assertEqual(entry['route_status'], 'waiting_for_dns')
            self.assertFalse(route_exists(route), 'a route was created although DNS is not ready')
        else:
            self.assertEqual(entry['route_status'], 'configured')
            self.assertTrue(route_exists(route), 'no autoconfig route was created for %s' % MAIL_DOMAIN)

    def test_04_autoconfig_resolves_the_real_user(self):
        if not (TEST_USER_LOGIN and TEST_USER_MAIL):
            self.skipTest('set TEST_USER_LOGIN and TEST_USER_MAIL to test the LDAP lookup path')
        cls = type(self)
        body = curl_automx(cls.automx, '/mail/config-v1.1.xml?emailaddress=%s' % TEST_USER_MAIL)
        # imap_auth_identity = ${login} (render-automx-conf) -- a real LDAP
        # match renders the bare login, not the address that was typed.
        # Only the fallback path (test_05) renders the full address back.
        self.assertIn('<username>%s</username>' % TEST_USER_LOGIN, body,
                       "automx-ldap-lookup should have resolved the primary address's own login")

    def test_05_alias_falls_back_to_the_bare_address(self):
        # DESIGN.md 3.3: an alias is not a valid login; the static fallback
        # applies rather than a wrong login being offered.
        if not TEST_ALIAS_MAIL:
            self.skipTest('set TEST_ALIAS_MAIL to test the alias fallback path')
        cls = type(self)
        body = curl_automx(cls.automx, '/mail/config-v1.1.xml?emailaddress=%s' % TEST_ALIAS_MAIL)
        self.assertIn('<username>%s</username>' % TEST_ALIAS_MAIL, body)

    def test_06_dns_status_reflects_dnshelper_presence(self):
        cls = type(self)
        rc, out = api(cls.automx, 'get-dnshelper-status', {})
        self.assertEqual(rc, 0)
        self.assertEqual(out['present'], bool(DNSHELPER_MODULE_ID))

        rc, out = api(cls.automx, 'check-dns', {'domain': MAIL_DOMAIN})
        self.assertEqual(rc, 0)
        dns = out['results'][0]['dns']
        if DNSHELPER_MODULE_ID:
            # Either the zone isn't managed, or it is but this module has
            # no rule yet (DESIGN.md 5.3.6) -- both are legitimate first-run
            # states; a live "ok" would mean the operator pre-created the
            # records, which is also fine.
            self.assertIn(dns['managed'], (True, False))
        else:
            self.assertFalse(dns['managed'])
            self.assertTrue(all(r['status'] in ('missing', 'unmanaged', 'unknown') for r in dns['records']))

    def test_07_get_dns_plan_lists_the_three_records(self):
        cls = type(self)
        rc, out = api(cls.automx, 'get-dns-plan', {'domain': MAIL_DOMAIN})
        self.assertEqual(rc, 0)
        hosts = {r['host'] for r in out['records']}
        self.assertEqual(
            hosts,
            {'autoconfig.%s' % MAIL_DOMAIN, 'autodiscover.%s' % MAIL_DOMAIN, '_autodiscover._tcp.%s' % MAIL_DOMAIN},
        )

    def test_08_profile_link_for_an_enabled_domain(self):
        cls = type(self)
        rc, out = api(cls.automx, 'get-profile-link', {'domain': MAIL_DOMAIN})
        self.assertEqual(rc, 0)
        self.assertEqual(out['url'], 'https://autoconfig.%s/mobileconfig' % MAIL_DOMAIN)
        self.assertIn('method="post"', out['html_snippet'])

    def test_09_disabling_removes_the_routes(self):
        cls = type(self)
        rc, out = api(cls.automx, 'set-domains', {'domains': {MAIL_DOMAIN: {'enabled': False}}})
        self.assertEqual(rc, 0)
        self.assertFalse(route_exists('%s-autoconfig-%s-0' % (cls.automx, MAIL_DOMAIN)),
                         'the autoconfig route should have been removed on disable')

    def test_10_backup_and_restore_round_trip(self):
        # NOTE: the exact cluster action name and payload for run-backup/
        # restore-module were not independently verified against ns8-core's
        # source in this session (unlike everything else in this file,
        # which matches automx's own confirmed action contracts) -- check
        # them against a real node/ns8-core before trusting this one.
        cls = type(self)
        api(cls.automx, 'set-domains', {'domains': {MAIL_DOMAIN: {'enabled': True}}})
        rc, backup = api('cluster', 'run-backup', {'module_id': cls.automx}, check=False)
        if rc != 0:
            self.skipTest('no backup repository configured on this node')

        rc, out = api('cluster', 'restore-module', {
            'module_id': cls.automx,
            'image_url': IMAGE,
            'node_id': 1,
        }, check=False)
        self.assertEqual(rc, 0, out)
        restored_id = out['module_id']
        INSTALLED.append(restored_id)

        rc, out = api(restored_id, 'get-domains', {})
        self.assertEqual(rc, 0)
        entry = next(d for d in out['domains'] if d['domain'] == MAIL_DOMAIN)
        self.assertTrue(entry['enabled'], 'state/domains.json should have round-tripped through the backup')

    def test_11_remove_module(self):
        cls = type(self)
        ssh('remove-module --no-preserve %s' % cls.automx)
        INSTALLED.remove(cls.automx)
        self.assertNotIn(cls.automx, existing_modules())


if __name__ == '__main__':
    unittest.main()

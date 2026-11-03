#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit tests for imageroot/bin/automx-dns-check (DESIGN.md 5.4). It runs INSIDE
# the automx-app container; here it's loaded directly (no .py extension, via
# importlib) with a fake "dns" package, since dnspython isn't installed where
# these tests run. The real library is exercised on a node.

import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(HERE, "..", "..")

AA, RD = 1, 2
NOERROR, NXDOMAIN, REFUSED = 0, 3, 5
TARGET = "node.example.net."
HOST = "autoconfig.example.com"


class FakeRdata:
    def __init__(self, text):
        self.text = text
        self.target = text

    def to_text(self):
        return self.text

    def __str__(self):
        return self.text


class FakeRrset(list):
    def __init__(self, name, rdtype, values):
        super().__init__(FakeRdata(v) for v in values)
        self.name = name
        self.rdtype = rdtype


class FakeResponse:
    def __init__(self, rcode=NOERROR, answer=(), flags=AA):
        self._rcode = rcode
        self.answer = list(answer)
        self.flags = flags

    def rcode(self):
        return self._rcode


def holds(*values, rtype="CNAME", name=HOST + "."):
    return FakeResponse(answer=[FakeRrset(name, rtype, values)])


class DnsCheckTestCase(unittest.TestCase):
    def setUp(self):
        self.nameservers = ["ns1.example.com.", "ns2.example.com."]
        self.servers = {}  # server address -> FakeResponse or exception
        self.resolved = {}  # (host, rtype) -> list of values or exception
        self.zone_error = None
        self.queries = []

        fake = types.ModuleType("dns")
        fake.exception = types.ModuleType("dns.exception")
        fake.exception.DNSException = type("DNSException", (Exception,), {})
        fake.resolver = types.ModuleType("dns.resolver")
        fake.resolver.NXDOMAIN = type("NXDOMAIN", (fake.exception.DNSException,), {})
        fake.resolver.NoAnswer = type("NoAnswer", (fake.exception.DNSException,), {})
        fake.resolver.zone_for_name = self.zone_for_name
        fake.resolver.resolve = self.resolve
        fake.flags = types.ModuleType("dns.flags")
        fake.flags.AA, fake.flags.RD = AA, RD
        fake.rcode = types.ModuleType("dns.rcode")
        fake.rcode.NOERROR, fake.rcode.NXDOMAIN = NOERROR, NXDOMAIN
        fake.rdatatype = types.ModuleType("dns.rdatatype")
        fake.rdatatype.from_text = lambda text: text
        fake.message = types.ModuleType("dns.message")
        fake.message.make_query = lambda host, rtype: types.SimpleNamespace(host=host, rtype=rtype, flags=RD | 4)
        fake.query = types.ModuleType("dns.query")
        fake.query.udp_with_fallback = self.udp_with_fallback
        self.fake = fake

        modules = {"dns": fake}
        modules.update({"dns." + n: getattr(fake, n) for n in ("exception", "flags", "message", "query", "rcode", "rdatatype", "resolver")})
        with mock.patch.dict(sys.modules, modules):
            loader = importlib.machinery.SourceFileLoader(
                "automx_dns_check", os.path.join(REPO_ROOT, "imageroot", "bin", "automx-dns-check")
            )
            spec = importlib.util.spec_from_loader("automx_dns_check", loader)
            self.script = importlib.util.module_from_spec(spec)
            loader.exec_module(self.script)

    def zone_for_name(self, host, lifetime=None):
        if self.zone_error:
            raise self.zone_error
        return "example.com."

    def resolve(self, name, rtype, lifetime=None):
        if rtype == "NS":
            return [FakeRdata(n) for n in self.nameservers]
        if rtype == "A":
            return [FakeRdata("addr-" + str(name))]
        if rtype == "AAAA":
            raise self.fake.resolver.NoAnswer()
        result = self.resolved.get((name, rtype), self.fake.resolver.NXDOMAIN())
        if isinstance(result, Exception):
            raise result
        return [FakeRdata(v) for v in result]

    def udp_with_fallback(self, query, address, timeout=None):
        self.queries.append((address, query))
        result = self.servers[address]
        if isinstance(result, Exception):
            raise result
        return result, False

    def both(self, response):
        self.servers = {"addr-" + n: response for n in self.nameservers}

    def check(self, value=TARGET, rtype="CNAME", host=HOST):
        return self.script.check_record(host, rtype, value)


class AuthoritativeTests(DnsCheckTestCase):
    def test_record_on_every_server_is_ok_despite_a_stale_resolver(self):
        self.both(holds(TARGET))
        self.resolved[(HOST, "CNAME")] = self.fake.resolver.NoAnswer()
        self.assertEqual(self.check(), "ok")

    def test_query_turns_recursion_off(self):
        self.both(holds(TARGET))
        self.check()
        self.assertTrue(self.queries)
        for _, query in self.queries:
            self.assertFalse(query.flags & RD)
            self.assertTrue(query.flags & 4)

    def test_nxdomain_and_nodata_are_missing(self):
        self.both(FakeResponse(rcode=NXDOMAIN))
        self.assertEqual(self.check(), "missing")
        self.both(FakeResponse())
        self.assertEqual(self.check(), "missing")

    def test_different_value_is_a_conflict(self):
        self.both(holds("other.example.net."))
        self.assertEqual(self.check(), "conflict")

    def test_target_compares_without_case_or_final_dot(self):
        self.both(holds("NODE.Example.NET"))
        self.assertEqual(self.check(), "ok")

    def test_srv_compares_all_fields(self):
        host = "_autodiscover._tcp.example.com"
        self.both(holds("0 0 443 node.example.net.", rtype="SRV", name=host + "."))
        self.assertEqual(self.check("0 0 443 node.example.net.", "SRV", host), "ok")
        self.assertEqual(self.check("0 0 8443 node.example.net.", "SRV", host), "conflict")

    def test_cname_answering_an_srv_query_is_not_the_srv(self):
        host = "_autodiscover._tcp.example.com"
        self.both(holds("elsewhere.example.net.", rtype="CNAME", name=host + "."))
        self.assertEqual(self.check("0 0 443 node.example.net.", "SRV", host), "missing")

    def test_a_server_without_the_record_yet_means_missing(self):
        self.servers = {"addr-ns1.example.com.": holds(TARGET), "addr-ns2.example.com.": FakeResponse(rcode=NXDOMAIN)}
        self.assertEqual(self.check(), "missing")

    def test_a_server_that_does_not_answer_is_ignored(self):
        self.servers = {"addr-ns1.example.com.": holds(TARGET), "addr-ns2.example.com.": OSError("unreachable")}
        self.assertEqual(self.check(), "ok")

    def test_non_authoritative_and_refused_answers_are_ignored(self):
        self.servers = {
            "addr-ns1.example.com.": FakeResponse(flags=0),
            "addr-ns2.example.com.": holds(TARGET),
        }
        self.assertEqual(self.check(), "ok")
        self.servers["addr-ns2.example.com."] = FakeResponse(rcode=REFUSED)
        self.resolved[(HOST, "CNAME")] = [TARGET]
        self.assertEqual(self.check(), "ok")
        self.assertTrue(self.script.direct_queries_failed)

    def test_nameserver_count_is_bounded(self):
        self.nameservers = ["ns%d.example.com." % i for i in range(10)]
        self.both(holds(TARGET))
        self.check()
        self.assertEqual(len(self.queries), self.script.MAX_NAMESERVERS)


class FallbackTests(DnsCheckTestCase):
    def test_unreachable_servers_fall_back_to_the_resolver(self):
        self.both(OSError("port 53 blocked"))
        self.resolved[(HOST, "CNAME")] = [TARGET]
        self.assertEqual(self.check(), "ok")

    def test_later_records_skip_the_direct_attempt(self):
        self.both(self.fake.exception.DNSException("timed out"))
        self.check()
        asked = len(self.queries)
        self.assertEqual(asked, 2)
        self.check()
        self.assertEqual(len(self.queries), asked)

    def test_zone_lookup_failure_falls_back(self):
        self.zone_error = self.fake.exception.DNSException("no zone")
        self.resolved[(HOST, "CNAME")] = ["other.example.net."]
        self.assertEqual(self.check(), "conflict")

    def test_resolver_statuses(self):
        self.zone_error = self.fake.exception.DNSException("no zone")
        self.assertEqual(self.check(), "missing")
        self.resolved[(HOST, "CNAME")] = self.fake.exception.DNSException("timed out")
        self.assertEqual(self.check(), "unknown")


class MainTests(DnsCheckTestCase):
    def run_main(self, records):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(records))), mock.patch.object(sys, "stdout", out):
            self.script.main()
        return json.loads(out.getvalue())

    def test_output_shape_and_unknown_type(self):
        self.both(holds(TARGET))
        records = [
            {"host": HOST, "type": "CNAME", "value": TARGET},
            {"host": HOST, "type": "TXT", "value": "x"},
        ]
        self.assertEqual(
            self.run_main(records),
            [{**records[0], "status": "ok"}, {**records[1], "status": "unknown"}],
        )

    def test_unexpected_error_on_one_record_keeps_the_others(self):
        self.both(holds(TARGET))
        with mock.patch.object(self.script, "check_record", side_effect=[ValueError("boom"), "ok"]):
            out = self.run_main([{"host": "a", "type": "CNAME", "value": "x"}, {"host": "b", "type": "SRV", "value": "y"}])
        self.assertEqual([r["status"] for r in out], ["unknown", "ok"])


if __name__ == "__main__":
    unittest.main()

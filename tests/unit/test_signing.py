#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Unit tests for automx.signing (DESIGN.md 2, v2): the checks that decide
# whether automx can sign Apple profiles with a certificate, mirroring the
# conditions under which automx itself refuses to load its configuration.

import datetime
import os
import shutil
import sys
import unittest
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "imageroot", "pypkg"))
sys.path.insert(0, HERE)
import stub_agent  # noqa: E402

_agent = stub_agent.build()
with mock.patch.dict(sys.modules, {"agent": _agent}):
    from automx import signing  # noqa: E402

NOW = datetime.datetime.now(datetime.timezone.utc)


def make_pair(key=None, days=(-1, 30), digital_signature=True, key_usage=True):
    key = key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "node.example.test")])
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW + datetime.timedelta(days=days[0]))
        .not_valid_after(NOW + datetime.timedelta(days=days[1]))
    )
    if key_usage:
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=digital_signature, content_commitment=False, key_encipherment=True,
                data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
    cert = builder.sign(key, hashes.SHA256())
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    )
    return cert_pem, key_pem


class ProblemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.good = make_pair()

    def test_rsa_2048_is_usable(self):
        self.assertIsNone(signing.problem(*self.good))

    def test_no_key_usage_extension_is_usable(self):
        self.assertIsNone(signing.problem(*make_pair(key_usage=False)))

    def test_ecdsa_cannot_sign(self):
        self.assertEqual(signing.problem(*make_pair(key=ec.generate_private_key(ec.SECP256R1()))), "not_rsa")

    def test_small_rsa_key(self):
        small = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        self.assertEqual(signing.problem(*make_pair(key=small)), "key_too_small")

    def test_key_from_another_certificate(self):
        other_cert, _ = make_pair()
        self.assertEqual(signing.problem(other_cert, self.good[1]), "key_mismatch")

    def test_expired(self):
        self.assertEqual(signing.problem(*make_pair(days=(-60, -1))), "expired")

    def test_key_usage_without_digital_signature(self):
        self.assertEqual(signing.problem(*make_pair(digital_signature=False)), "no_digital_signature")

    def test_garbage(self):
        self.assertEqual(signing.problem(b"not a cert", b"not a key"), "unreadable")


@unittest.skipUnless(shutil.which("openssl"), "needs the openssl command")
class TrustedTests(unittest.TestCase):
    def test_self_signed_is_not_trusted(self):
        cert_pem, _ = make_pair()
        self.assertFalse(signing.trusted(cert_pem))

    def test_no_certificate(self):
        self.assertFalse(signing.trusted(b""))


class FetchTests(unittest.TestCase):
    def test_decodes_the_first_certificate(self):
        import base64

        output = {
            "fqdn": "node.example.test",
            "type": "internal",
            "obtained": True,
            "certificates": [
                {"cert": base64.b64encode(b"CERT").decode(), "key": base64.b64encode(b"KEY").decode()},
                {"cert": "b3RoZXI=", "key": "b3RoZXI="},
            ],
        }
        run = mock.Mock(return_value={"exit_code": 0, "output": output, "error": ""})
        with mock.patch.object(signing.agent.tasks, "run", run), \
                mock.patch.object(signing.agent, "resolve_agent_id", return_value="module/traefik1"):
            self.assertEqual(signing.fetch("node.example.test"), ("internal", b"CERT", b"KEY"))
        self.assertEqual(run.call_args.kwargs["data"], {"fqdn": "node.example.test"})


if __name__ == "__main__":
    unittest.main()

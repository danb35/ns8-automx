#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Mobileconfig signing (DESIGN.md 2, v2 scope). automx signs profiles
# in-process when [automx] names a certificate and key (automx
# docs/configuration.md, "Mobileconfig signing"): an RSA key of at least
# 2048 bits, a currently valid signer that permits digital signatures, the
# key file owner-only. Any of that failing prevents automx from loading its
# configuration at all, so it is checked here first and signing is skipped
# (with the reason recorded) rather than taking the service down.
#
# The certificate is the one Traefik already holds for the service host
# (the node FQDN by default), which this module's own Autodiscover route
# asks Let's Encrypt for. Reading it needs traefik@node:certadm. Traefik's
# ACME key type is its default, RSA 4096; an uploaded custom certificate
# may be ECDSA, which automx cannot sign with.

import base64
import datetime
import os
import re
import subprocess
import tempfile

import agent

MIN_KEY_BITS = 2048
PEM_CERT = re.compile(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----\s*", re.S)


def fetch(fqdn):
    """(type, cert_pem, key_pem) from Traefik's get-certificate: type is
    "internal" (ACME), "custom" (uploaded) or "selfsigned" (Traefik's
    fallback when it has nothing for fqdn). cert_pem may hold a chain."""
    response = agent.tasks.run(
        agent_id=agent.resolve_agent_id("traefik@node"),
        action="get-certificate",
        data={"fqdn": fqdn},
        extra={"isNotificationHidden": True},
    )
    agent.assert_exp(response["exit_code"] == 0, f"get-certificate failed for {fqdn}")
    output = response["output"]
    first = output["certificates"][0]
    return output["type"], base64.b64decode(first["cert"]), base64.b64decode(first["key"])


def _not_valid(cert):
    # cryptography >= 42 has the *_utc properties. The NS8 agent's version
    # depends on the node's Python: 39.0.0 on older cores, 46.0.3 on a
    # Debian 13 node (2026-09-29).
    before = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before.replace(tzinfo=datetime.timezone.utc)
    after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    return not before <= now <= after


def problem(cert_pem, key_pem):
    """None if automx can sign with this pair, else an error code."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    try:
        cert = x509.load_pem_x509_certificate(cert_pem)
        key = serialization.load_pem_private_key(key_pem, password=None)
    except (ValueError, TypeError):
        return "unreadable"
    if not isinstance(key, rsa.RSAPrivateKey):
        return "not_rsa"
    if key.key_size < MIN_KEY_BITS:
        return "key_too_small"
    if key.public_key().public_numbers() != cert.public_key().public_numbers():
        return "key_mismatch"
    if _not_valid(cert):
        return "expired"
    try:
        usage = cert.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound:
        return None
    if not usage.digital_signature:
        return "no_digital_signature"
    return None


def trusted(cert_pem):
    """True/False: whether the chain verifies against this node's system
    trust store (a stand-in for the clients' own, which is what decides
    whether a profile shows as verified), None if that can't be checked."""
    blocks = PEM_CERT.findall(cert_pem)
    if not blocks:
        return False
    with tempfile.TemporaryDirectory() as tmpdir:
        leaf = os.path.join(tmpdir, "leaf.pem")
        chain = os.path.join(tmpdir, "chain.pem")
        with open(leaf, "wb") as f:
            f.write(blocks[0])
        with open(chain, "wb") as f:
            f.write(b"".join(blocks[1:]))
        args = ["openssl", "verify"]
        if len(blocks) > 1:
            args += ["-untrusted", chain]
        try:
            result = subprocess.run(args + [leaf], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
    return result.returncode == 0

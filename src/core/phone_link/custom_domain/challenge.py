
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import os
import ssl
import tempfile
from typing import Dict, Optional

import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ObjectIdentifier

from src.core.phone_link.custom_domain.hello import ACME_TLS_1

logger = structlog.get_logger()

ACME_IDENTIFIER_OID = ObjectIdentifier("1.3.6.1.5.5.7.1.31")


def challenge_cert(domain: str, digest: bytes,
                   key: Optional[ec.EllipticCurvePrivateKey] = None) -> "tuple[x509.Certificate, ec.EllipticCurvePrivateKey]":
    if len(digest) != 32:
        raise ValueError("the acmeIdentifier digest is 32 bytes")
    key = key or ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, domain)])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(domain)]), critical=False)
            .add_extension(x509.UnrecognizedExtension(ACME_IDENTIFIER_OID, b"\x04\x20" + digest), critical=True)
            .sign(key, hashes.SHA256()))
    return cert, key


class ChallengeResponder:

    def __init__(self) -> None:
        self._server: Optional[asyncio.AbstractServer] = None
        self._open: Dict[str, bytes] = {}
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._context.set_alpn_protocols([ACME_TLS_1])

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("the challenge responder is not started")
        return self._server.sockets[0].getsockname()[1]

    @property
    def has_open(self) -> bool:
        return bool(self._open)

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0, ssl=self._context)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._open.clear()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        with contextlib.suppress(ConnectionError, OSError, ssl.SSLError):
            await writer.wait_closed()

    def _load(self, cert: x509.Certificate, key: ec.EllipticCurvePrivateKey) -> None:
        pem = (cert.public_bytes(serialization.Encoding.PEM) + key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        fd, path = tempfile.mkstemp(prefix="acme-alpn-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(pem)
            self._context.load_cert_chain(path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)

    async def publish(self, domain: str, digest: bytes) -> None:
        cert, key = challenge_cert(domain, digest)
        await asyncio.to_thread(self._load, cert, key)
        self._open[domain] = digest
        logger.info("phone_link_alpn_challenge_open")

    async def clear(self, domain: str) -> None:
        self._open.pop(domain, None)

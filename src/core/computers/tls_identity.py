
from __future__ import annotations

import base64
import datetime
import hashlib
import os
import secrets
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

import structlog
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from src.core.relay_identity.device_key import DeviceKey

logger = structlog.get_logger()

LINK_INFO = b"carnivore link tls v1"
_NOT_BEFORE = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
_NOT_AFTER = datetime.datetime(2126, 1, 1, tzinfo=datetime.timezone.utc)
_CN_PREFIX = "carnivore-link "


class CertRejected(ValueError):
    pass


@dataclass(frozen=True)
class LinkCert:

    link_fid: str
    cert_sha256: str
    der: bytes
    raw_pub: bytes


@dataclass
class LinkIdentity:

    cert: LinkCert
    key_path: Path
    cert_path: Path


def link_fid_for(raw_pub: bytes) -> str:
    return base64.b32encode(hashlib.sha256(raw_pub).digest()[:16]).decode("ascii").rstrip("=").lower()


def _raw_pub(public: Ed25519PublicKey) -> bytes:
    return public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _name_for(link_fid: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _CN_PREFIX + link_fid)])


def build_cert_der(private: Ed25519PrivateKey) -> bytes:
    pub = private.public_key()
    raw = _raw_pub(pub)
    name = _name_for(link_fid_for(raw))
    builder = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(pub)
        .serial_number(int.from_bytes(hashlib.sha256(raw).digest()[:16], "big") | 1)
        .not_valid_before(_NOT_BEFORE).not_valid_after(_NOT_AFTER)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False, data_encipherment=False,
            key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False),
            critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
                       critical=False)
    )
    return builder.sign(private, None).public_bytes(serialization.Encoding.DER)


def validate_peer_cert(der: bytes, *, own_link_fid: str) -> LinkCert:
    try:
        cert = x509.load_der_x509_certificate(bytes(der))
    except (ValueError, TypeError) as exc:
        raise CertRejected("the certificate does not parse") from exc
    public = cert.public_key()
    if not isinstance(public, Ed25519PublicKey):
        raise CertRejected("the certificate key is not Ed25519")
    raw = _raw_pub(public)
    link_fid = link_fid_for(raw)
    expected = _name_for(link_fid)
    if cert.subject != expected or cert.issuer != expected:
        raise CertRejected("the certificate name does not match its key")
    try:
        public.verify(cert.signature, cert.tbs_certificate_bytes)
    except InvalidSignature as exc:
        raise CertRejected("the certificate signature is bad") from exc
    try:
        basic = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
        usage = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    except x509.ExtensionNotFound as exc:
        raise CertRejected("the certificate lacks a required extension") from exc
    if basic.ca:
        raise CertRejected("the certificate is a certificate authority")
    if usage.key_cert_sign or usage.crl_sign:
        raise CertRejected("the certificate may sign certificates")
    if set(eku) != {ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH} or len(eku) != 2:
        raise CertRejected("the certificate extended usage is wrong")
    if link_fid == own_link_fid:
        raise CertRejected("the certificate is this computer's own")
    return LinkCert(link_fid=link_fid, cert_sha256=hashlib.sha256(bytes(der)).hexdigest(),
                    der=bytes(der), raw_pub=raw)


def write_private(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _read_or_none(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def link_stem(install_id: str) -> str:
    return "link-" + install_id[:12]


def write_identity(fed_key: DeviceKey, salt: bytes, key_path: Path, cert_path: Path) -> LinkCert:
    private = Ed25519PrivateKey.from_private_bytes(fed_key.derive_seed(LINK_INFO, salt))
    der = build_cert_der(private)
    key_pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    cert_pem = x509.load_der_x509_certificate(der).public_bytes(serialization.Encoding.PEM)
    if _read_or_none(key_path) != key_pem:
        write_private(key_path, key_pem)
    if _read_or_none(cert_path) != cert_pem:
        write_private(cert_path, cert_pem)
    return validate_peer_cert(der, own_link_fid="")


def _stored_identity(key_path: Path, cert_path: Path) -> Optional[LinkIdentity]:
    key_pem, cert_pem = _read_or_none(key_path), _read_or_none(cert_path)
    if key_pem is None or cert_pem is None:
        return None
    try:
        private = serialization.load_pem_private_key(key_pem, password=None)
        der = x509.load_pem_x509_certificate(cert_pem).public_bytes(serialization.Encoding.DER)
        cert = validate_peer_cert(der, own_link_fid="")
    except (ValueError, TypeError, CertRejected):
        return None
    if not isinstance(private, Ed25519PrivateKey) or _raw_pub(private.public_key()) != cert.raw_pub:
        return None
    return LinkIdentity(cert=cert, key_path=key_path, cert_path=cert_path)


def ensure_link_identity(fed_key: DeviceKey, install_id: str, fed_dir: Path) -> LinkIdentity:
    stem = link_stem(install_id)
    key_path, cert_path = fed_dir / (stem + "-key.pem"), fed_dir / (stem + "-cert.pem")
    if (fed_dir / (stem + "-next-cert.pem")).exists():
        stored = _stored_identity(key_path, cert_path)
        if stored is not None:
            return stored
    salt_path = fed_dir / (stem + "-salt")
    salt = _read_or_none(salt_path)
    if salt is None or len(salt) != 32:
        salt = secrets.token_bytes(32)
        write_private(salt_path, salt)
    cert = write_identity(fed_key, salt, key_path, cert_path)
    return LinkIdentity(cert=cert, key_path=key_path, cert_path=cert_path)


def pinned_certs(ders: Iterable[bytes], *, own_link_fid: str) -> list:
    good = []
    for der in ders:
        try:
            good.append(validate_peer_cert(der, own_link_fid=own_link_fid))
        except CertRejected as exc:
            logger.warning("computers_pin_skipped", why=str(exc))
    return good


def _pem_bundle(certs: Sequence[LinkCert]) -> str:
    return "".join(ssl.DER_cert_to_PEM_cert(c.der) for c in certs)


def _base(purpose: ssl.Purpose, identity: LinkIdentity) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if purpose is ssl.Purpose.CLIENT_AUTH else ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.verify_flags |= ssl.VERIFY_X509_STRICT
    ctx.check_hostname = False
    ctx.options |= ssl.OP_NO_TICKET
    ctx.load_cert_chain(str(identity.cert_path), str(identity.key_path))
    return ctx


def server_link_ctx(identity: LinkIdentity, pins: Sequence[LinkCert]) -> ssl.SSLContext:
    if not pins:
        raise ValueError("a link listener needs at least one pinned certificate")
    ctx = _base(ssl.Purpose.CLIENT_AUTH, identity)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cadata=_pem_bundle(pins))
    ctx.num_tickets = 0
    return ctx


def client_link_ctx(identity: LinkIdentity, pins: Sequence[LinkCert]) -> ssl.SSLContext:
    if not pins:
        raise ValueError("a link dial needs at least one pinned certificate")
    ctx = _base(ssl.Purpose.SERVER_AUTH, identity)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cadata=_pem_bundle(pins))
    return ctx


def server_join_ctx(identity: LinkIdentity) -> ssl.SSLContext:
    ctx = _base(ssl.Purpose.CLIENT_AUTH, identity)
    ctx.verify_mode = ssl.CERT_NONE
    ctx.num_tickets = 0
    return ctx


def client_join_ctx() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.options |= ssl.OP_NO_TICKET
    return ctx

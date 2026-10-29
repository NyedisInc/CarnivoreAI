
from __future__ import annotations

import datetime
import socket
import ssl
import threading
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from src.core.computers import tls_identity as t
from src.core.relay_identity.device_key import DeviceKey, DeviceKeyUnavailable

OWN = "x" * 26


def _identity(tmp_path: Path, seed_byte: int, iid: str = "install-aaaaaaaa"):
    d = tmp_path / f"fed{seed_byte}"
    d.mkdir(mode=0o700)
    return t.ensure_link_identity(DeviceKey.from_seed(bytes([seed_byte]) * 32), iid, d)


def _cert(key, *, ca=False, subject=None, usage_sign=False, eku=None, name_fid=None) -> bytes:
    pub = key.public_key()
    fid = name_fid or t.link_fid_for(t._raw_pub(pub) if hasattr(pub, "public_bytes") and isinstance(key, Ed25519PrivateKey) else b"")
    name = subject or x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "carnivore-link " + fid)])
    b = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(pub).serial_number(7)
         .not_valid_before(datetime.datetime(2026, 1, 1)).not_valid_after(datetime.datetime(2126, 1, 1))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
         .add_extension(x509.KeyUsage(True, False, False, False, False, usage_sign, usage_sign, False, False), critical=True)
         .add_extension(x509.ExtendedKeyUsage(eku or [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False))
    return b.sign(key, None if isinstance(key, Ed25519PrivateKey) else hashes.SHA256()).public_bytes(serialization.Encoding.DER)


def _handshake(server_ctx, client_ctx) -> str:
    a, b = socket.socketpair()
    out = {}

    def serve():
        try:
            with server_ctx.wrap_socket(a, server_side=True) as s:
                s.sendall(s.recv(4))
                out["ticket"] = None
        except (ssl.SSLError, OSError) as exc:
            out["server"] = type(exc).__name__

    th = threading.Thread(target=serve)
    th.start()
    try:
        with client_ctx.wrap_socket(b, server_hostname="x") as c:
            c.sendall(b"ping")
            assert c.recv(4) == b"ping"
            assert c.version() == "TLSv1.3"
        return "ok"
    except (ssl.SSLError, OSError) as exc:
        return type(exc).__name__
    finally:
        th.join(5)
        a.close()
        b.close()


def test_mtls_two_anchors_and_third_refused(tmp_path):
    main, m1, m2, stranger = (_identity(tmp_path, n) for n in (1, 2, 3, 4))
    srv = t.server_link_ctx(main, [m1.cert, m2.cert])
    assert srv.num_tickets == 0 and srv.options & ssl.OP_NO_TICKET
    assert _handshake(srv, t.client_link_ctx(m1, [main.cert])) == "ok"
    assert _handshake(srv, t.client_link_ctx(m2, [main.cert])) == "ok"
    assert _handshake(srv, t.client_link_ctx(stranger, [main.cert])) != "ok"
    assert _handshake(srv, t.client_link_ctx(m1, [stranger.cert])) != "ok"
    assert _handshake(t.server_join_ctx(main), t.client_join_ctx()) == "ok"


def test_validate_accepts_own_build_and_is_stable(tmp_path):
    ident = _identity(tmp_path, 1)
    again = t.ensure_link_identity(DeviceKey.from_seed(bytes([1]) * 32), "install-aaaaaaaa", ident.key_path.parent)
    assert again.cert.der == ident.cert.der
    assert oct(ident.key_path.stat().st_mode & 0o777) == "0o600"
    assert (ident.key_path.parent / "link-install-aaaa-salt").exists()
    with pytest.raises(t.CertRejected):
        t.validate_peer_cert(ident.cert.der, own_link_fid=ident.cert.link_fid)


def test_validate_refuses_bad_certs():
    k = Ed25519PrivateKey.generate()
    good = _cert(k)
    assert t.validate_peer_cert(good, own_link_fid=OWN).link_fid
    with pytest.raises(t.CertRejected):
        t.validate_peer_cert(_cert(k, ca=True), own_link_fid=OWN)
    with pytest.raises(t.CertRejected):
        t.validate_peer_cert(_cert(k, name_fid="a" * 26), own_link_fid=OWN)
    with pytest.raises(t.CertRejected):
        t.validate_peer_cert(good[:-9], own_link_fid=OWN)
    with pytest.raises(t.CertRejected):
        t.validate_peer_cert(b"", own_link_fid=OWN)
    with pytest.raises(t.CertRejected):
        t.validate_peer_cert(_cert(k, usage_sign=True), own_link_fid=OWN)
    with pytest.raises(t.CertRejected):
        t.validate_peer_cert(_cert(k, eku=[ExtendedKeyUsageOID.SERVER_AUTH]), own_link_fid=OWN)
    rsa_key = rsa.generate_private_key(65537, 2048)
    with pytest.raises(t.CertRejected):
        t.validate_peer_cert(_cert(rsa_key, name_fid="b" * 26), own_link_fid=OWN)
    tampered = bytearray(good)
    tampered[-3] ^= 1
    with pytest.raises(t.CertRejected):
        t.validate_peer_cert(bytes(tampered), own_link_fid=OWN)
    assert t.pinned_certs([good, b"junk"], own_link_fid=OWN)[0].der == good
    assert len(t.pinned_certs([good, b"junk"], own_link_fid=OWN)) == 1


def test_no_pins_no_context(tmp_path):
    ident = _identity(tmp_path, 1)
    with pytest.raises(ValueError):
        t.server_link_ctx(ident, [])


def test_derive_seed():
    key = DeviceKey.from_seed(bytes([9]) * 32)
    a = key.derive_seed(b"i", b"s" * 32)
    assert len(a) == 32 and a == key.derive_seed(b"i", b"s" * 32)
    assert a != key.derive_seed(b"i", b"t" * 32) and a != key.derive_seed(b"j", b"s" * 32)
    assert bytes([9]) * 32 not in repr(key).encode()
    with pytest.raises(DeviceKeyUnavailable):
        DeviceKey(raw_pub=key.raw_pub, device_id=key.device_id, _private=key._private).derive_seed(b"i", b"s")

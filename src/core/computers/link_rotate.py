
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

import structlog
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.core.computers import join_proto, store
from src.core.computers.tls_identity import (CertRejected, LinkCert, LinkIdentity, link_stem, validate_peer_cert,
                                             write_identity, write_private)
from src.core.federation.grants import Grant, GrantError, decode_public_key
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.relay_identity.device_key import DeviceKey, unb64url

log = structlog.get_logger(__name__)

LINK_CERT_PREFIX = b"carnivore federation v1 link-cert\x00"
LINK_CERT_PATH = "/federation/link-cert"
SWAP_AFTER_SECONDS = 7 * 24 * 3600
IDLE, WAITING, SWAPPED = "idle", "waiting", "swapped"


class LinkCertRefused(ValueError):

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class Staged:

    sha: str
    staged_at: float
    acked: Tuple[str, ...] = ()


def link_cert_message(cert_der: bytes) -> bytes:
    return LINK_CERT_PREFIX + hashlib.sha256(cert_der).digest()


def verify_link_cert(public_key: str, cert_der: bytes, signature: object) -> None:
    try:
        raw = decode_public_key(public_key)
    except GrantError:
        raise LinkCertRefused("link_cert_signature") from None
    sig = unb64url(signature, 64)
    if sig is None:
        raise LinkCertRefused("link_cert_signature")
    try:
        Ed25519PublicKey.from_public_bytes(raw).verify(sig, link_cert_message(cert_der))
    except (InvalidSignature, ValueError):
        raise LinkCertRefused("link_cert_signature") from None


def accept(conn: sqlite3.Connection, grant: Grant, cert_b64: object, signature: object, *, own_link_fid: str) -> LinkCert:
    try:
        der = join_proto.b64d(cert_b64, field="cert_der")
    except join_proto.ProtoError:
        raise LinkCertRefused("link_cert_malformed") from None
    if not 0 < len(der) <= 2048:
        raise LinkCertRefused("link_cert_malformed")
    verify_link_cert(grant.public_key, der, signature)
    try:
        cert = validate_peer_cert(der, own_link_fid=own_link_fid)
    except CertRejected:
        raise LinkCertRefused("cert_invalid") from None
    row = store.get(conn, grant.peer_install_id)
    if row is None or row.transport != "tls" or row.cert_der is None:
        raise LinkCertRefused("computer_not_linked_tls", 409)
    if cert.cert_sha256 in (row.cert_sha256, row.next_cert_sha256):
        return cert
    if any(r.peer_install_id != row.peer_install_id and cert.cert_sha256 in (r.cert_sha256, r.next_cert_sha256)
           for r in store.list_rows(conn)):
        raise LinkCertRefused("cert_in_use", 409)
    store.set_next_cert(conn, row.peer_install_id, cert.der, cert.cert_sha256)
    return cert


def promote(open_db: Callable[[], sqlite3.Connection], iid: str, sha: str) -> bool:
    with closing(open_db()) as conn:
        row = store.get(conn, iid)
        if row is None or row.next_cert_der is None or row.next_cert_sha256 != sha:
            return False
        try:
            cert = validate_peer_cert(row.next_cert_der, own_link_fid="")
        except CertRejected:
            log.warning("link_rotate_next_cert_invalid", peer=iid[:8])
            return False
        done = store.promote_next_cert(conn, iid, link_fid=cert.link_fid)
    if done:
        log.info("link_cert_promoted", peer=iid[:8])
    return done


def _paths(fed_dir: Path, iid: str) -> dict:
    stem = link_stem(iid)
    return {"salt": fed_dir / (stem + "-salt"), "key": fed_dir / (stem + "-key.pem"), "cert": fed_dir / (stem + "-cert.pem"),
            "next_salt": fed_dir / (stem + "-next-salt"), "next_key": fed_dir / (stem + "-next-key.pem"),
            "next_cert": fed_dir / (stem + "-next-cert.pem"), "state": fed_dir / (stem + "-rotation.json")}


def _der_of(path: Path) -> Optional[bytes]:
    try:
        return x509.load_pem_x509_certificate(path.read_bytes()).public_bytes(serialization.Encoding.DER)
    except (OSError, ValueError):
        return None


def read_staged(fed_dir: Path, iid: str) -> Optional[Staged]:
    paths = _paths(fed_dir, iid)
    der = _der_of(paths["next_cert"])
    if der is None:
        return None
    sha, staged_at, acked = hashlib.sha256(der).hexdigest(), 0.0, ()
    try:
        staged_at = paths["next_cert"].stat().st_mtime
        state = json.loads(paths["state"].read_text())
        if isinstance(state, dict) and state.get("sha") == sha:
            staged_at = float(state.get("staged_at", staged_at))
            acked = tuple(a for a in state.get("acked", []) if isinstance(a, str))
    except (OSError, ValueError, TypeError):
        pass
    return Staged(sha, staged_at, acked)


def _write_state(fed_dir: Path, iid: str, staged: Staged) -> None:
    body = json.dumps({"sha": staged.sha, "staged_at": staged.staged_at, "acked": list(staged.acked)}).encode()
    write_private(_paths(fed_dir, iid)["state"], body)


def stage(new_key: DeviceKey, iid: str, fed_dir: Path, *, now: Optional[float] = None) -> LinkCert:
    paths = _paths(fed_dir, iid)
    paths["next_cert"].unlink(missing_ok=True)
    salt = secrets.token_bytes(32)
    write_private(paths["next_salt"], salt)
    cert = write_identity(new_key, salt, paths["next_key"], paths["next_cert"])
    _write_state(fed_dir, iid, Staged(cert.cert_sha256, time.time() if now is None else now))
    log.info("link_cert_staged", link_fid=cert.link_fid)
    return cert


def clear_staged(fed_dir: Path, iid: str) -> None:
    paths = _paths(fed_dir, iid)
    for name in ("next_cert", "next_key", "next_salt", "state"):
        paths[name].unlink(missing_ok=True)


def swap(identity: LinkIdentity, iid: str, fed_dir: Path) -> LinkCert:
    paths = _paths(fed_dir, iid)
    der = _der_of(paths["next_cert"])
    if der is None:
        raise OSError("no staged link certificate")
    cert = validate_peer_cert(der, own_link_fid="")
    for src, dst in (("next_salt", "salt"), ("next_key", "key"), ("next_cert", "cert")):
        os.replace(paths[src], paths[dst])
    paths["state"].unlink(missing_ok=True)
    identity.cert = cert
    log.info("link_cert_swapped", link_fid=cert.link_fid)
    return cert


async def _tell(client: Any, der: bytes, signer: DeviceKey) -> bool:
    body = {"cert_der": join_proto.b64e(der), "sig": signer.sign(link_cert_message(der))}
    try:
        reply = await client.request("POST", LINK_CERT_PATH, json=body)
    except (PeerUnreachable, PeerRefused, asyncio.TimeoutError) as exc:
        log.info("link_cert_send_failed", error_type=type(exc).__name__)
        return False
    if reply.status_code != 200:
        log.warning("link_cert_refused", status=reply.status_code)
    return reply.status_code == 200


async def run_step(*, links: Any, open_db: Callable[[], sqlite3.Connection], fed_dir: Path, iid: str, signer: DeviceKey,
                   identity: LinkIdentity, now: Optional[float] = None) -> str:
    staged = await asyncio.to_thread(read_staged, fed_dir, iid)
    if staged is None:
        return IDLE
    if staged.sha == identity.cert.cert_sha256:
        await asyncio.to_thread(clear_staged, fed_dir, iid)
        return IDLE

    def rows() -> List[store.LinkRow]:
        with closing(open_db()) as conn:
            return [r for r in store.list_rows(conn) if r.transport == "tls"]

    der = await asyncio.to_thread(_der_of, _paths(fed_dir, iid)["next_cert"])
    tls_rows = await asyncio.to_thread(rows)
    acked = set(staged.acked)
    if der is not None:
        for row in tls_rows:
            client = links.client(row.peer_install_id) if row.peer_install_id not in acked else None
            if client is not None and await _tell(client, der, signer):
                acked.add(row.peer_install_id)
    if acked != set(staged.acked):
        staged = Staged(staged.sha, staged.staged_at, tuple(sorted(acked)))
        await asyncio.to_thread(_write_state, fed_dir, iid, staged)
    waiting = [r for r in tls_rows if r.peer_install_id not in acked]
    if waiting and (time.time() if now is None else now) - staged.staged_at < SWAP_AFTER_SECONDS:
        return WAITING
    await asyncio.to_thread(swap, identity, iid, fed_dir)
    return SWAPPED


async def after_federation_rotation(new_key: DeviceKey) -> None:
    from src.core.computers import runtime

    rt = runtime.active()
    if rt is None:
        return
    try:
        await rt.rotate_link(new_key)
    except (OSError, ValueError, sqlite3.Error) as exc:
        log.warning("link_rotate_failed", error_type=type(exc).__name__)

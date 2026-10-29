
from __future__ import annotations

import asyncio
import hashlib
import ssl
import uuid
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

import structlog

from src.core.computers import commit, join_identity, join_proto, store
from src.core.computers.commit import JoinRefused, Links, PackSettingsPort, PeerId
from src.core.computers.join_proto import JoinKeys, JoinPake, ProtoError
from src.core.computers.tls_identity import CertRejected, LinkIdentity, client_join_ctx, validate_peer_cert
from src.core.federation import grants
from src.core.relay_identity.device_key import DeviceKey

log = structlog.get_logger(__name__)


class JoinFailed(Exception):

    def __init__(self, code: str, left: Optional[int] = None) -> None:
        super().__init__(code)
        self.code, self.left = code, left


@dataclass(frozen=True)
class JoinOutcome:

    main_install_id: str
    main_label: str
    kind: str


def _error_of(msg: Dict[str, Any]) -> None:
    if msg.get("t") == "error":
        code = msg.get("code")
        left = msg.get("left")
        raise JoinFailed(code if code in join_proto.ERROR_CODES else "refused", left if isinstance(left, int) else None)


def _check_rules(open_db: commit.OpenDb, own_iid: str, main_iid: str, main_fid: str, require_existing_grant: bool) -> Tuple[str, Optional[str], str]:
    if main_iid == own_iid:
        raise JoinFailed("refused")
    with closing(open_db()) as conn:
        live = [g for g in grants.list_grants(conn) if g.revoked_at is None]
        if any(g.peer_install_id != main_iid for g in live) or store.members_tls(conn):
            log.info("computer_join_has_peers")
            raise JoinFailed("join_has_peers")
        existing = next((g for g in live if g.peer_install_id == main_iid), None)
    if existing is not None and existing.fid != main_fid:
        log.warning("computer_join_main_key_differs", iid=main_iid[:8])
        raise JoinFailed("main_mismatch")
    if existing is None:
        if require_existing_grant:
            raise JoinFailed("needs_owner")
        return uuid.uuid4().hex, None, "new"
    return existing.grant_id, existing.remote_grant_id, "migrate"


async def join(*, relay_path: str, listen_port: int, listen_addresses: Sequence[str], mode: str, identity: LinkIdentity, fed_key: DeviceKey, public_key: str, own_iid: str,
               own_label: str, open_db: commit.OpenDb, links: Links, pack: PackSettingsPort, code: Optional[str] = None,
               secret: Optional[bytes] = None, invite_id: Optional[str] = None, expect_cert_k: Optional[str] = None,
               expect_fid: Optional[str] = None, require_existing_grant: bool = False, app_version: str = "", notify: Optional[commit.Notify] = None) -> JoinOutcome:
    pw = join_proto.password(mode, code=code, secret=secret)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(relay_path, ssl=client_join_ctx(), server_hostname="",
                                         ssl_handshake_timeout=join_proto.TLS_HANDSHAKE_TIMEOUT),
            join_proto.TLS_HANDSHAKE_TIMEOUT + 2)
    except (OSError, asyncio.TimeoutError, ssl.SSLError) as exc:
        log.info("computer_join_relay_connect_failed", reason=type(exc).__name__)
        raise JoinFailed("unreachable") from None
    try:
        return await asyncio.wait_for(
            _run(reader, writer, pw, mode=mode, invite_id=invite_id, expect_cert_k=expect_cert_k, expect_fid=expect_fid, require_existing_grant=require_existing_grant,
                 identity=identity, fed_key=fed_key, public_key=public_key, own_iid=own_iid, own_label=own_label, open_db=open_db,
                 links=links, pack=pack, app_version=app_version, notify=notify, listen_port=listen_port,
                 listen_addresses=listen_addresses), join_proto.SESSION_TIMEOUT)
    except (ProtoError, asyncio.TimeoutError, ConnectionError, ssl.SSLError, OSError) as exc:
        log.info("computer_join_client_dropped", reason=type(exc).__name__)
        raise JoinFailed("unreachable") from None
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, ssl.SSLError, OSError):
            pass


async def _run(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, pw: bytes, *, mode: str, invite_id: Optional[str],
               expect_cert_k: Optional[str], expect_fid: Optional[str], require_existing_grant: bool, identity: LinkIdentity, fed_key: DeviceKey, public_key: str,
               own_iid: str, own_label: str, open_db: commit.OpenDb, links: Links, pack: PackSettingsPort, app_version: str,
               notify: Optional[commit.Notify], listen_port: int, listen_addresses: Sequence[str]) -> JoinOutcome:
    ssl_obj = writer.get_extra_info("ssl_object")
    cert_der_main = ssl_obj.getpeercert(binary_form=True) if ssl_obj is not None else None
    if not cert_der_main:
        raise JoinFailed("unreachable")
    fps = join_proto.fp_server(cert_der_main)
    if expect_cert_k is not None and fps.hex()[:32] != expect_cert_k.lower():
        raise JoinFailed("main_mismatch")
    pake = JoinPake("joiner", pw)
    msg_a = pake.start()
    writer.write(join_proto.MAGIC)
    await join_proto.write_message(writer, join_proto.hello(mode=mode, msg_a=msg_a, fid=fed_key.device_id, invite_id=invite_id))
    reply = await join_proto.read_message(reader, join_proto.MESSAGE_TIMEOUT)
    _error_of(reply)
    spake = join_proto.check_spake(reply)
    keys_t = join_proto.transcript(mode=mode, invite_id=invite_id or "", msg_a=msg_a, msg_b=spake["msg_b"], join_id=spake["join_id"],
                                   fps=fps, joiner_fid=fed_key.device_id)
    keys = JoinKeys(pake.finish(spake["msg_b"]), keys_t)
    await join_proto.write_message(writer, join_proto.confirm_j(keys.mac_j()))
    reply = await join_proto.read_message(reader, join_proto.MESSAGE_TIMEOUT)
    _error_of(reply)
    confirm = join_proto.check_confirm(reply, from_main=True)
    if not keys.equal(confirm["mac"], keys.mac_m(confirm["main"])):
        await _abort(writer, "main_mismatch")
    main_iid, main_fid = confirm["main"]["install_id"], confirm["main"]["fid"]
    if expect_fid is not None and main_fid != expect_fid:
        await _abort(writer, "main_mismatch")
    try:
        own_grant, existing, kind = await asyncio.to_thread(_check_rules, open_db, own_iid, main_iid, main_fid, require_existing_grant)
    except JoinFailed as exc:
        await _abort(writer, "refused" if exc.code == "join_has_peers" else exc.code, raise_code=exc.code)
    await join_proto.write_message(writer, join_identity.build_identity(
        role="J", t=keys_t, keys=keys, key=fed_key, install_id=own_iid, label=own_label, public_key=public_key,
        cert_der=identity.cert.der, grant_id=own_grant, app_version=app_version,
        extra={"existing_grant_id": existing, "listen": {"port": listen_port, "addresses": list(listen_addresses)}}))
    reply = await join_proto.read_message(reader, join_proto.MESSAGE_TIMEOUT)
    _error_of(reply)
    try:
        body, cert_der = join_identity.verify_identity(reply, t=keys_t, keys=keys, sender_role="M")
        if body["install_id"] != main_iid or body["fid"] != main_fid or hashlib.sha256(cert_der).digest() != fps:
            raise ProtoError("main identity does not match message 4 or the TLS certificate")
        cert = validate_peer_cert(cert_der, own_link_fid=identity.cert.link_fid)
        settings = body.get("settings")
        if not isinstance(settings, dict):
            raise ProtoError("pack settings missing")
    except (ProtoError, CertRejected):
        await _abort(writer, "refused")
    main = PeerId(main_iid, body["label"], body["public_key"], cert_der, cert.link_fid, body["grant_id"])
    try:
        await commit.joiner_provisional(open_db, links, identity=identity, own_iid=own_iid, main=main, own_grant_id=own_grant, kind=kind,
                                        settings=settings, addresses=(), link_port=listen_port, pack=pack, notify=notify)
    except JoinRefused:
        await _abort(writer, "refused")
    except BaseException:
        await _abort(writer, "refused", raises=False)
        raise
    try:
        await join_proto.write_message(writer, join_proto.done())
    except (ConnectionError, ssl.SSLError, OSError):
        log.info("computer_join_done_not_sent")
    return JoinOutcome(main_iid, main.label, kind)


async def _abort(writer: asyncio.StreamWriter, code: str, *, raises: bool = True, raise_code: Optional[str] = None) -> None:
    try:
        await join_proto.write_message(writer, join_proto.abort(code if code in join_proto.ABORT_CODES else "refused"))
    except (ConnectionError, ssl.SSLError, OSError):
        pass
    if raises:
        raise JoinFailed(raise_code or code)

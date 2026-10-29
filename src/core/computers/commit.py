
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Sequence

import structlog

from src.core import setup_state
from src.core.computers import membership, store
from src.core.computers.link_listener import Member
from src.core.computers.tls_identity import (CertRejected, LinkIdentity, client_link_ctx, pinned_certs, server_link_ctx,
                                             validate_peer_cert)
from src.core.federation import grants, peer_hosts
from src.core.pack.machines import settings_doc
from src.core.trail_entry import utc_now

log = structlog.get_logger(__name__)

PROVISIONAL_SECONDS = 15 * 60
SWEEP_EVERY_SECONDS = 60

OpenDb = Callable[[], sqlite3.Connection]
Notify = Callable[[str], None]


class JoinRefused(Exception):

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Links(Protocol):

    async def start_initiator(self, row: peer_hosts.PeerRow) -> None: ...
    async def remove(self, peer_install_id: str) -> None: ...


class PackSettingsPort(Protocol):

    def settings(self) -> settings_doc.PackSettings: ...
    def signature(self) -> Optional[Dict[str, Any]]: ...
    def mint(self, changes: Dict[str, Any], base: Optional[settings_doc.PackSettings] = None) -> settings_doc.PackSettings: ...
    def adopt(self, doc: settings_doc.PackSettings, signature: Optional[Dict[str, Any]] = None) -> bool: ...


class PinListener(Protocol):

    async def set_members(self, members: Sequence[Member]) -> str: ...


@dataclass(frozen=True)
class PeerId:

    install_id: str
    label: str
    public_key: str
    cert_der: bytes
    link_fid: str
    grant_id: str


@dataclass(frozen=True)
class MainResult:

    grant_id: str
    settings: Dict[str, Any]
    kind: str


def listener_members(conn: sqlite3.Connection, own_link_fid: str) -> List[Member]:
    members: List[Member] = []
    for row in store.members_tls(conn):
        grant = grants.live_for_peer(conn, row.peer_install_id)
        certs = pinned_certs([d for d in (row.cert_der, row.next_cert_der) if d], own_link_fid=own_link_fid)
        if grant is None or not certs or certs[0].cert_sha256 != row.cert_sha256:
            log.warning("computers_member_not_pinned", iid=row.peer_install_id[:8])
            continue
        members.append(Member(row.peer_install_id, grant.grant_id, certs[0], certs[1] if len(certs) > 1 else None))
    return members


def _unrevoke(conn: sqlite3.Connection, grant_id: str) -> None:
    conn.execute(f"UPDATE {grants.FEDERATION_GRANTS_TABLE} SET revoked_at = NULL WHERE grant_id = ?", (grant_id,))


def _set_remote_grant_id(conn: sqlite3.Connection, grant_id: str, remote_grant_id: Optional[str]) -> None:
    conn.execute(f"UPDATE {grants.FEDERATION_GRANTS_TABLE} SET remote_grant_id = ? WHERE grant_id = ?", (remote_grant_id, grant_id))


class _Undo:

    def __init__(self, open_db: OpenDb) -> None:
        self._open_db = open_db
        self._steps: List[Callable[[sqlite3.Connection], None]] = []

    def add(self, step: Callable[[sqlite3.Connection], None]) -> None:
        self._steps.append(step)

    def run(self) -> None:
        with closing(self._open_db()) as conn:
            while self._steps:
                step = self._steps.pop()
                try:
                    step(conn)
                except (sqlite3.Error, OSError, grants.GrantError) as exc:
                    log.error("computers_commit_undo_failed", error=type(exc).__name__)


def _write_grant_pair(conn: sqlite3.Connection, undo: _Undo, *, peer: PeerId, own_grant_id: str, label: str, initiator: bool) -> None:
    old = grants.live_for_peer(conn, peer.install_id)
    old_host = peer_hosts.get(conn, peer.install_id)
    if old is not None and old.grant_id == own_grant_id and old.public_key == peer.public_key:
        _set_remote_grant_id(conn, own_grant_id, peer.grant_id)
        undo.add(lambda c: _set_remote_grant_id(c, own_grant_id, old.remote_grant_id))
    else:
        if old is not None:
            grants.revoke(conn, old.grant_id)
            undo.add(lambda c: _unrevoke(c, old.grant_id))
        grants.create_grant(conn, peer_install_id=peer.install_id, public_key=peer.public_key, label=label,
                            remote_grant_id=peer.grant_id, grant_id=own_grant_id)
        undo.add(lambda c: grants.delete_grant(c, own_grant_id))
    kept: Dict[str, Any] = {}
    if old_host is not None:
        kept = {"ssh_target": old_host.ssh_target, "ssh_port": old_host.ssh_port, "peer_port": old_host.peer_port,
                "protocol": old_host.peer_protocol, "back_kind": old_host.back_kind}
    peer_hosts.upsert(conn, install_id=peer.install_id, label=label, grant_id=peer.grant_id, fid=grants.get_grant(conn, own_grant_id).fid,  # type: ignore[union-attr]
                      initiator=initiator, **kept)
    if old_host is None:
        undo.add(lambda c: peer_hosts.delete(c, peer.install_id))
    else:
        undo.add(lambda c: peer_hosts.upsert(c, install_id=old_host.peer_install_id, label=old_host.label, grant_id=old_host.peer_grant_id,
                                           fid=old_host.peer_fid, initiator=old_host.initiator, ssh_target=old_host.ssh_target,
                                           ssh_port=old_host.ssh_port, peer_port=old_host.peer_port, protocol=old_host.peer_protocol,
                                           back_kind=old_host.back_kind))


def _put_row(conn: sqlite3.Connection, undo: _Undo, row: store.LinkRow) -> None:
    before = store.get(conn, row.peer_install_id)
    store.put(conn, row)
    undo.add(lambda c: store.put(c, before) if before is not None else store.delete(c, row.peer_install_id))


def classify_join(conn: sqlite3.Connection, *, own_iid: str, own_link_fid: str, joiner: PeerId) -> str:
    if joiner.install_id == own_iid or joiner.link_fid == own_link_fid:
        raise JoinRefused("refused", "the joining computer claims this computer's identity")
    live = grants.live_for_peer(conn, joiner.install_id)
    if live is None:
        return "new"
    if live.public_key != joiner.public_key:
        log.warning("peer_identity_changed", iid=joiner.install_id[:8])
        raise JoinRefused("peer_identity_changed", "that computer is already paired with another key; remove it first")
    return "migrate"


def _main_writes(open_db: OpenDb, undo: _Undo, *, identity: LinkIdentity, own_iid: str, joiner: PeerId, kind: str,
                 pack: PackSettingsPort, announced_grant_id: Optional[str], member_addresses: Sequence[str] = (),
                 member_port: Optional[int] = None) -> MainResult:
    try:
        cert = validate_peer_cert(joiner.cert_der, own_link_fid=identity.cert.link_fid)
    except CertRejected as exc:
        raise JoinRefused("refused", str(exc)) from None
    if cert.link_fid != joiner.link_fid:
        raise JoinRefused("refused", "the certificate does not belong to the announced link fid")
    with closing(open_db()) as conn:
        pins = pinned_certs([d for r in store.members_tls(conn) for d in (r.cert_der, r.next_cert_der) if d],
                            own_link_fid=identity.cert.link_fid)
        try:
            server_link_ctx(identity, [*pins, cert])
        except (ValueError, OSError) as exc:
            raise JoinRefused("refused", "the link context could not be built") from exc
        old_grant, old_host = grants.live_for_peer(conn, joiner.install_id), peer_hosts.get(conn, joiner.install_id)
        consistent = (kind == "migrate" and old_grant is not None and old_grant.remote_grant_id == joiner.grant_id
                      and old_host is not None and old_host.peer_grant_id == joiner.grant_id)
        grant_id = old_grant.grant_id if consistent else (announced_grant_id or uuid.uuid4().hex)  # type: ignore[union-attr]
        pinned = pack.mint({"master_install_id": pack.settings().master_install_id})
        before = store.get(conn, joiner.install_id)
        _put_row(conn, undo, store.LinkRow(
            joiner.install_id, "member", "tls", "", join_kind=kind,
            prev_initiator=None if kind == "new" or old_host is None else int(old_host.initiator),
            cert_der=cert.der, cert_sha256=cert.cert_sha256, link_fid=cert.link_fid, addresses=tuple(member_addresses),
            link_port=member_port, inbound_control=before.inbound_control if before is not None else 1, joined_at=utc_now()))
        if not consistent:
            _write_grant_pair(conn, undo, peer=joiner, own_grant_id=grant_id, label=joiner.label, initiator=False)
        return MainResult(grant_id=grant_id, settings=pinned.model_dump(mode="json"), kind=kind)


async def main_provisional(open_db: OpenDb, listener: PinListener, *, identity: LinkIdentity, own_iid: str, joiner: PeerId,
                           kind: str, pack: PackSettingsPort, announced_grant_id: Optional[str] = None,
                           notify: Optional[Notify] = None, member_addresses: Sequence[str] = (),
                           member_port: Optional[int] = None) -> MainResult:
    undo = _Undo(open_db)
    try:
        result = await asyncio.to_thread(_main_writes, open_db, undo, identity=identity, own_iid=own_iid, joiner=joiner,
                                         kind=kind, pack=pack, announced_grant_id=announced_grant_id,
                                         member_addresses=member_addresses, member_port=member_port)
        await listener.set_members(await asyncio.to_thread(_members_of, open_db, identity.cert.link_fid))
    except JoinRefused:
        raise
    except BaseException:
        await asyncio.to_thread(undo.run)
        try:
            await listener.set_members(await asyncio.to_thread(_members_of, open_db, identity.cert.link_fid))
        except (ValueError, OSError) as exc:
            log.error("computers_commit_repin_failed", error=type(exc).__name__)
        raise
    _notify(notify)
    log.info("computer_join_provisional", iid=joiner.install_id[:8], kind=kind)
    return result


def _members_of(open_db: OpenDb, own_link_fid: str) -> List[Member]:
    with closing(open_db()) as conn:
        return listener_members(conn, own_link_fid)


def _notify(notify: Optional[Notify]) -> None:
    if notify is not None:
        notify("computers")
        notify("pack_machines")


def _joiner_writes(open_db: OpenDb, undo: _Undo, *, identity: LinkIdentity, own_iid: str, main: PeerId, own_grant_id: str, kind: str,
                   settings: Dict[str, Any], addresses: Sequence[str], link_port: Optional[int], pack: PackSettingsPort
                   ) -> peer_hosts.PeerRow:
    try:
        cert = validate_peer_cert(main.cert_der, own_link_fid=identity.cert.link_fid)
    except CertRejected as exc:
        raise JoinRefused("refused", str(exc)) from None
    if cert.link_fid != main.link_fid:
        raise JoinRefused("refused", "the certificate does not belong to the announced link fid")
    doc = settings_doc.from_dict(settings)
    if doc is None:
        raise JoinRefused("refused", "main sent an unusable pack document")
    if doc.rev[1] == own_iid:
        log.warning("computers_join_forged_pack_doc", iid=main.install_id[:8], rev=list(doc.rev))
        raise JoinRefused("refused", "main sent a pack document that names this computer as its editor")
    try:
        client_link_ctx(identity, [cert])
    except (ValueError, OSError) as exc:
        raise JoinRefused("refused", "the link context could not be built") from exc
    with closing(open_db()) as conn:
        old_host, old_grant = peer_hosts.get(conn, main.install_id), grants.live_for_peer(conn, main.install_id)
        consistent = (kind == "migrate" and old_grant is not None and old_grant.grant_id == own_grant_id
                      and old_grant.remote_grant_id == main.grant_id and old_host is not None and old_host.peer_grant_id == main.grant_id)
        if old_grant is not None and old_grant.public_key != main.public_key:
            raise JoinRefused("peer_identity_changed", "that computer is already paired with another key; remove it first")
        previous, previous_sig = pack.settings(), pack.signature()
        pack.adopt(doc)
        if kind == "migrate":
            undo.add(lambda _c: pack.adopt(previous, previous_sig))
        else:
            undo.add(lambda _c: pack.mint({"master_install_id": own_iid}, previous))
        before = store.get(conn, main.install_id)
        _put_row(conn, undo, store.LinkRow(
            main.install_id, "main", "tls", "", join_kind=kind,
            prev_initiator=None if kind == "new" or old_host is None else int(old_host.initiator),
            cert_der=cert.der, cert_sha256=cert.cert_sha256, link_fid=cert.link_fid, addresses=tuple(addresses), link_port=link_port,
            inbound_control=before.inbound_control if before is not None else 1, joined_at=utc_now()))
        if consistent:
            peer_hosts.set_initiator(conn, main.install_id, True)
            was = old_host.initiator  # type: ignore[union-attr]
            undo.add(lambda c: peer_hosts.set_initiator(c, main.install_id, was))
        else:
            _write_grant_pair(conn, undo, peer=main, own_grant_id=own_grant_id, label=main.label, initiator=True)
        row = peer_hosts.get(conn, main.install_id)
        assert row is not None
        return row


async def joiner_provisional(open_db: OpenDb, links: Links, *, identity: LinkIdentity, own_iid: str, main: PeerId, own_grant_id: str,
                             kind: str, settings: Dict[str, Any], addresses: Sequence[str], link_port: Optional[int],
                             pack: PackSettingsPort, notify: Optional[Notify] = None) -> None:
    undo = _Undo(open_db)
    try:
        row = await asyncio.to_thread(_joiner_writes, open_db, undo, identity=identity, own_iid=own_iid, main=main,
                                      own_grant_id=own_grant_id, kind=kind, settings=settings, addresses=addresses,
                                      link_port=link_port, pack=pack)
        await links.start_initiator(row)
    except JoinRefused:
        raise
    except BaseException:
        await asyncio.to_thread(undo.run)
        await links.remove(main.install_id)
        if kind == "migrate":
            await _restart_ssh_initiator(open_db, links, main.install_id)
        raise
    _notify(notify)
    log.info("computer_join_provisional", iid=main.install_id[:8], kind=kind, side="joiner")


async def _restart_ssh_initiator(open_db: OpenDb, links: Links, iid: str) -> None:
    def read() -> Optional[peer_hosts.PeerRow]:
        with closing(open_db()) as conn:
            return peer_hosts.get(conn, iid)

    host = await asyncio.to_thread(read)
    if host is not None and host.initiator:
        await links.start_initiator(host)


async def main_final(open_db: OpenDb, links: Links, iid: str, *, notify: Optional[Notify] = None) -> bool:
    def read() -> Optional[store.LinkRow]:
        with closing(open_db()) as conn:
            return store.get(conn, iid)

    row = await asyncio.to_thread(read)
    if row is None or row.role != "member" or row.transport != "tls":
        raise JoinRefused("refused", "no member row for that computer")
    first = row.provisional
    if first and row.join_kind == "migrate":
        await links.remove(iid)

    def write() -> None:
        with closing(open_db()) as conn:
            if first and row.join_kind == "migrate":
                peer_hosts.set_initiator(conn, iid, False)
            store.touch_link(conn, iid, first=first)

    await asyncio.to_thread(write)
    if first:
        _notify(notify)
        log.info("computer_join_final", iid=iid[:8], kind=row.join_kind, side="main")
    return first


def _write_marker(path: Path, main_iid: str, joined_at: str) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"main": main_iid, "joined_at": joined_at}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


async def joiner_final(open_db: OpenDb, main_iid: str, *, config_path: Path, revoke_refresh_tokens: Callable[[], Awaitable[Any]],
                       notify: Optional[Notify] = None) -> bool:
    def read() -> Optional[store.LinkRow]:
        with closing(open_db()) as conn:
            return store.get(conn, main_iid)

    row = await asyncio.to_thread(read)
    if row is None or row.role != "main" or row.transport != "tls":
        raise JoinRefused("refused", "no main row for that computer")
    if not row.provisional:
        return False
    sentinel = config_path.parent / setup_state.PAIRED_SENTINEL_NAME
    was_set_up = await asyncio.to_thread(sentinel.exists)
    await asyncio.to_thread(_write_marker, setup_state.joined_marker_path(config_path), main_iid, row.joined_at or utc_now())
    if was_set_up:
        await asyncio.to_thread(lambda: sentinel.unlink(missing_ok=True))
        await revoke_refresh_tokens()
        membership.request_rebind()

    def stamp() -> None:
        with closing(open_db()) as conn:
            store.touch_link(conn, main_iid, first=True)

    await asyncio.to_thread(stamp)
    _notify(notify)
    log.info("computer_join_final", iid=main_iid[:8], kind=row.join_kind, side="joiner", d4=was_set_up)
    return True


def _revert_rows(conn: sqlite3.Connection, row: store.LinkRow, pack: PackSettingsPort, own_iid: str) -> None:
    iid = row.peer_install_id
    if row.join_kind == "migrate":
        if row.prev_initiator is not None:
            peer_hosts.set_initiator(conn, iid, bool(row.prev_initiator))
    else:
        live = grants.live_for_peer(conn, iid)
        if live is not None:
            grants.revoke(conn, live.grant_id)
        peer_hosts.delete(conn, iid)
    store.delete(conn, iid)
    if row.role == "main" and row.join_kind != "migrate":
        pack.mint({"master_install_id": own_iid})


async def sweep(open_db: OpenDb, *, identity: LinkIdentity, own_iid: str, pack: PackSettingsPort, links: Links,
                listener: Optional[PinListener] = None, max_age: float = PROVISIONAL_SECONDS, notify: Optional[Notify] = None) -> List[str]:
    def run() -> List[store.LinkRow]:
        done: List[store.LinkRow] = []
        with closing(open_db()) as conn:
            for row in store.provisional_older_than(conn, max_age):
                _revert_rows(conn, row, pack, own_iid)
                done.append(row)
        return done

    reverted = await asyncio.to_thread(run)
    for row in reverted:
        if row.role == "main":
            await links.remove(row.peer_install_id)
            if row.join_kind == "migrate":
                await _restart_ssh_initiator(open_db, links, row.peer_install_id)
        log.warning("computer_join_reverted", iid=row.peer_install_id[:8], kind=row.join_kind)
    if any(r.role == "member" for r in reverted) and listener is not None:
        await listener.set_members(await asyncio.to_thread(_members_of, open_db, identity.cert.link_fid))
    if reverted:
        _notify(notify)
    return [r.peer_install_id for r in reverted]


from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import structlog

from src.core.federation import fed_key, grants, pair_sas, pairing, peer_hosts, peer_sockets
from src.core.federation.grants import GrantError
from src.core.federation.peer_client import PeerClient, PeerUnreachable
from src.core.federation.peer_dial import InitiatorTransport
from src.core.federation.peer_link import LinkDown
from src.core.hosts import ssh_exec, ssh_forward
from src.core.hosts.ssh_forward import ForwardError
from src.core.hosts.ssh_exec import SshDestination

logger = structlog.get_logger()

_FILE_RE = re.compile(r"/[A-Za-z0-9._/ +-]+/federation/pair-([0-9a-f]{16})")
_CODE_RE = re.compile(r"[A-Z0-9]{8}")


class PairingFailed(Exception):
    """The pairing could not finish. ``code`` is a wire code (``pair_code_invalid`` ...)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class NeedsTypedCode(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class TypedCode:

    nonce: str
    code: str


@dataclass(frozen=True)
class PairPending:

    nonce: str
    proof: str
    answer: dict
    our_grant_id: str
    sas: str


@dataclass(frozen=True)
class PairResult:

    host_key: str
    peer_install_id: str
    our_grant_id: str
    peer_grant_id: str
    label: str


async def _run_out(*argv: str) -> Optional[str]:
    try:
        proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    except (OSError, asyncio.TimeoutError):
        return None
    return out.decode(errors="replace") if proc.returncode == 0 else None


async def host_key_pinned(dest: SshDestination) -> bool:
    config = await _run_out("/usr/bin/ssh", "-G", *(["-p", str(dest.port)] if dest.port else []), "--", dest.target)
    if config is None:
        return False
    values = {}
    for line in config.splitlines():
        key, _, value = line.partition(" ")
        values.setdefault(key.lower(), value.strip())
    host, port = values.get("hostname", ""), values.get("port", "22")
    alias = values.get("hostkeyalias", "")
    name = alias if alias and alias != "none" else (host if port == "22" else f"[{host}]:{port}")
    files = [f for key in ("userknownhostsfile", "globalknownhostsfile") for f in values.get(key, "").split()
             if f != "none"]
    if not host or not files:
        return False
    for path in files:
        if await _run_out("/usr/bin/ssh-keygen", "-F", name, "-f", os.path.expanduser(path)) is not None:
            return True
    return False


async def _begin_over_pair_socket(transport: InitiatorTransport) -> Tuple[str, str]:
    dest, cp = transport.dest, transport.master.control_path
    found = await ssh_forward.glob_remote(dest, cp, "$HOME/.carnivore/fed/pair-*.sock")
    if len(found) != 1:
        raise NeedsTypedCode("no_pair_socket" if not found else "ambiguous_instance")
    try:
        local = await transport.master.forward_local_unix(transport.pair_path, found[0])
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(local), timeout=5)
        try:
            writer.write(b"BEGIN\n")
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=8)
        finally:
            writer.close()
    except (ForwardError, OSError, asyncio.TimeoutError):
        raise NeedsTypedCode("user_mismatch") from None
    try:
        answer = json.loads(line)
    except ValueError:
        raise NeedsTypedCode("user_mismatch") from None
    if answer.get("error") == "pair_rate_limited":
        raise PairingFailed("pair_rate_limited", "the peer says too many pairing starts")
    nonce, path = str(answer.get("nonce", "")), str(answer.get("file", ""))
    match = _FILE_RE.fullmatch(path)
    if match is None or match.group(1) != nonce:
        raise PairingFailed("pair_response_invalid", "the peer answered an odd code file path")
    return nonce, path


async def _read_code_file(transport: InitiatorTransport, path: str) -> str:
    result = await ssh_exec.run_process(
        ssh_exec.mux_argv(transport.dest, transport.master.control_path, "cat -- " + shlex.quote(path)),
        timeout=10.0, verb="pair-code", host=transport.dest.target)
    code = result.stdout_text.strip().upper()
    if not result.ok or not _CODE_RE.fullmatch(code):
        raise NeedsTypedCode("user_mismatch")
    return code


def _persist(open_db: Callable[[], sqlite3.Connection], *, our_grant_id: str, answer: dict, dest: SshDestination,
             remote_port: int, back_kind: str) -> "tuple[str, list[str]]":
    replaced = []
    with closing(open_db()) as conn:
        old = grants.live_for_peer(conn, answer["install_id"])
        if old is not None and old.public_key != answer["public_key"]:
            raise PairingFailed("peer_identity_changed", "a live grant for that install id holds a different key; unpair it first")
        if old is not None:
            grants.revoke(conn, old.grant_id)
            replaced.append(old.grant_id)
        grant = grants.create_grant(conn, peer_install_id=answer["install_id"], public_key=answer["public_key"],
                                    label=answer.get("label", ""), remote_grant_id=answer["grant_id"],
                                    grant_id=our_grant_id)
        row = peer_hosts.upsert(conn, install_id=answer["install_id"], label=answer.get("label", ""),
                                grant_id=answer["grant_id"], fid=grant.fid, initiator=True,
                                ssh_target=dest.target, ssh_port=dest.port, peer_port=remote_port,
                                protocol=answer.get("protocol"), back_kind=back_kind)
    return row.key, replaced


def _check_answer(answer: object, expected_fid: str) -> bytes:
    if not isinstance(answer, dict):
        raise PairingFailed("pair_response_invalid", "the peer's answer is not an object")
    try:
        peer_raw = grants.decode_public_key(answer["public_key"])
    except (GrantError, KeyError):
        raise PairingFailed("pair_response_invalid", "the peer's answer is missing or holds a bad key") from None
    if not all(isinstance(answer.get(f), str) for f in ("grant_id", "install_id")):
        raise PairingFailed("pair_response_invalid", "the peer's answer is missing its ids")
    fid = fed_key.fid_for(peer_raw)
    if answer.get("fid") != fid or (expected_fid and fid != expected_fid):
        raise PairingFailed("pair_response_invalid", "the peer's key fingerprint does not match its key or the one advertised")
    return peer_raw


async def pair(*, transport: InitiatorTransport, open_db: Callable[[], sqlite3.Connection], install_id: str,
               key: "fed_key.DeviceKey", label: str, remote_port: int, pinned_before: bool,
               fid_matches_pinned: bool = False, expected_fid: str = "",
               typed: Optional[TypedCode] = None) -> PairPending:
    plan = pairing.plan_pairing(host_key_pinned_before=pinned_before, fid_matches_pinned=fid_matches_pinned,
                                ssh_user_matches=True)
    if typed is None and plan.proof == pairing.PROOF_TYPED:
        raise NeedsTypedCode("first_contact")
    proof = pairing.PROOF_TYPED if typed is not None else pairing.PROOF_SSH_FILE
    route = await transport.up_local()
    client = PeerClient(route, grant_id="", peer_install_id="", sign=lambda _m: "")
    try:
        if typed is None:
            nonce, path = await _begin_over_pair_socket(transport)
            typed = TypedCode(nonce, await _read_code_file(transport, path))
        our_grant_id = uuid.uuid4().hex
        done = await client.public("POST", "/federation/pair/complete", json={
            "nonce": typed.nonce, "code": typed.code, "install_id": install_id, "label": label,
            "public_key": fed_key.public_key_b64(key), "grant_id": our_grant_id,
            "protocol": pairing.PROTOCOL_MAJOR})
    except PeerUnreachable as exc:
        raise LinkDown(str(exc)) from None
    if done.status_code == 409:
        detail = done.json().get("detail") if done.headers.get("content-type", "").startswith("application/json") else None
        code = detail.get("code") if isinstance(detail, dict) else None
        if code == "peer_identity_changed":
            raise PairingFailed(code, "the peer holds a different key for this install; revoke its grant there first")
        raise PairingFailed("protocol_mismatch", "the protocol major versions differ")
    if done.status_code != 200:
        raise PairingFailed("pair_code_invalid", "the peer did not accept the pairing code")
    answer = done.json()
    peer_raw = _check_answer(answer, expected_fid)
    return PairPending(typed.nonce, proof, answer, our_grant_id,
                       pair_sas.compute_sas(key.raw_pub, peer_raw, typed.nonce))


async def activate(*, pending: PairPending, dest: SshDestination, back_kind: str,
                   open_db: Callable[[], sqlite3.Connection], remote_port: int) -> PairResult:
    answer = pending.answer
    try:
        host_key, replaced = await asyncio.to_thread(_persist, open_db, our_grant_id=pending.our_grant_id, answer=answer,
                                                     dest=dest, remote_port=remote_port,
                                                     back_kind=back_kind)
    except GrantError as exc:
        raise PairingFailed(exc.code, str(exc)) from None
    for old_grant in replaced:
        await peer_sockets.close_grant(old_grant)
    logger.info("federation_pair_driven", host=host_key, replaced=len(replaced))
    return PairResult(host_key, answer["install_id"], pending.our_grant_id, answer["grant_id"], answer.get("label", ""))


async def finish(*, transport: InitiatorTransport, key: "fed_key.DeviceKey", nonce: str, accept: bool) -> str:
    """
    Output: the peer's state (``active``, ``awaiting_owner``, ``cancelled``).
    Raises: PairingFailed ``pair_pending_gone`` (the peer no longer holds that pairing), LinkDown.
    Example: await finish(transport=t, key=k, nonce=n, accept=True)
    """
    route = await transport.up_local()
    client = PeerClient(route, grant_id="", peer_install_id="", sign=lambda _m: "")
    try:
        done = await client.public("POST", "/federation/pair/finish", json={
            "nonce": nonce, "accept": accept, "signature": key.sign(pair_sas.finish_message(nonce, accept))})
    except PeerUnreachable as exc:
        raise LinkDown(str(exc)) from None
    if done.status_code == 404:
        raise PairingFailed("pair_pending_gone", "the peer no longer holds this pairing")
    if done.status_code != 200:
        raise PairingFailed("pair_response_invalid", "the peer did not accept the confirmation")
    return str(done.json().get("state", ""))

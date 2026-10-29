"""The door (#1530 J5c, design 4.3): the same-uid unix socket the installer and the Electron shell talk to.

Socket ``fed_dir()/door-<instance tag>.sock`` (the runtime picks the path), directory 0700, socket 0600, peer uid checked with
``LOCAL_PEERCRED`` (``pair_socket.peer_uid``). Never TCP. One JSON line in; JSON lines out (a ``relay`` streams each status change until the job ends), then close:

* ``{"op":"status"}`` -> ``{"state","error","main_label","main_iid","tries_left","candidates","setup_status","joined","join_relay":1}``
  (a ``finding`` state with ``candidates`` filled means several packs answered: the caller picks one and joins again with ``candidate_fid``;
  ``tries_left`` is set on ``wrong_code``). ``join_relay`` marks a build that joins through the helper (flip design 1.1). While a job
  waits for its relay it also carries ``job`` (its id), ``mode`` (``code`` or ``link``), ``targets`` (``[[host, port], ...]``, link mode) and ``candidate_fid``.
  ``"hold":true`` keeps the connection open after the answer: when it closes while that job still waits (the helper exited, or its
  Terminal window was closed) the job ends ``no_relay`` at once instead of after 120 s.
* ``{"op":"join","code"|"link":...,"candidate_fid"?,"totp"?}`` -> ONE status line (state ``waiting_relay``), or ``{"error": <code>}``.
  State ``unpaired``: allowed. ``paired`` (set up): allowed with a valid ``totp``; without one only the re-join of a main this host
  already holds a live grant for, else the job ends ``needs_owner``. ``joined``: ``already_joined``. Nothing runs until a ``relay``.
* ``{"op":"relay","job":id,"relay":path,"address":str,"expect_fid":str|null}`` -> status lines until the job ends; only while a job waits
  (else ``{"error":"no_join_waiting"}``, which is also the answer when ``job`` is not the waiting job's id). ``path`` must be ``<door dir>/relay-<16 hex>.sock``, a socket this uid owns.
* ``{"op":"relay_fail","job":id,"code":c,"candidates"?:[...]}`` -> one status line; ``c`` in ``no_pack``, ``unreachable``, ``local_network_blocked``, ``several``
  (a "look" job, #1622, takes ``no_pack``, ``local_network_blocked`` and ``found`` instead; ``found`` ends it ``finding`` with the packs).
* ``{"op":"login"}`` -> ``{"access_token","refresh_token","expires_in"}`` only when joined; else ``{"error":"not_joined"}``.

No ``leave`` op. No log line carries a code, link, token or ``totp``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import stat
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional

import structlog

from src.core.computers import join_job, membership
from src.core.federation.pair_socket import peer_uid

log = structlog.get_logger(__name__)

MAX_LINE = 4096
READ_TIMEOUT_S = 5.0
STREAM_POLL_S = 0.2
RELAY_NAME = re.compile(r"^relay-[0-9a-f]{16}\.sock$")
RELAY_ADDRESS = re.compile(r"^[A-Za-z0-9.:-]{1,255}$")
RELAY_FID = re.compile(r"^[a-z2-7]{16,64}$")


def _wants_hold(line: bytes) -> bool:
    try:
        req = json.loads(line)
    except ValueError:
        return False
    return isinstance(req, dict) and req.get("op") == "status" and req.get("hold") is True


class Door:

    def __init__(self, path: str, *, totp_ok: Callable[[str], Awaitable[bool]], login: Callable[[Any], Awaitable[Dict[str, Any]]],
                 setup_status: Callable[[], str] = lambda: "unknown", refresh_store: Callable[[], Any] = lambda: None,
                 uid: Optional[int] = None) -> None:
        self.path = path
        self._totp_ok, self._login, self._setup_status, self._refresh_store = totp_ok, login, setup_status, refresh_store
        self._uid = os.getuid() if uid is None else uid
        self._server: Optional[asyncio.AbstractServer] = None

    async def start(self) -> None:
        directory = os.path.dirname(self.path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        with contextlib.suppress(FileNotFoundError):
            if stat.S_ISSOCK(os.lstat(self.path).st_mode):
                os.unlink(self.path)
        self._server = await asyncio.start_unix_server(self._serve, path=self.path)
        os.chmod(self.path, 0o600)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.path)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            sock = writer.get_extra_info("socket")
            if sock is None or peer_uid(sock) != self._uid:
                log.warning("door_refused_uid")
                return
            line = await asyncio.wait_for(reader.readline(), READ_TIMEOUT_S)
            if not line or len(line) > MAX_LINE:
                return
            last: Dict[str, Any] = {}
            async for answer in self.respond(line):
                last = answer
                writer.write(json.dumps(answer).encode() + b"\n")
                await writer.drain()
            if _wants_hold(line) and isinstance(last.get("job"), str):
                await self._hold(reader, last["job"])
        except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
            log.info("door_io", error_type=type(exc).__name__)
        finally:
            writer.close()

    async def _hold(self, reader: asyncio.StreamReader, job_id: str) -> None:
        with contextlib.suppress(asyncio.TimeoutError, ConnectionError, OSError):
            await asyncio.wait_for(reader.read(), join_job.RELAY_WAIT_SECONDS + READ_TIMEOUT_S)
        join_job.end_waiting_by_id(job_id, "no_relay")

    async def respond(self, line: bytes) -> AsyncIterator[Dict[str, Any]]:
        try:
            req = json.loads(line)
        except ValueError:
            req = None
        op = req.get("op") if isinstance(req, dict) else None
        if op == "status":
            yield self._status()
        elif op == "join":
            async for doc in self._join(req):
                yield doc
        elif op == "relay":
            async for doc in self._relay(req):
                yield doc
        elif op == "relay_fail":
            yield self._relay_fail(req)
        elif op == "login":
            yield await self._do_login()
        else:
            yield {"error": "bad_request"}

    def _status(self) -> Dict[str, Any]:
        out = dict(join_job.join_status())
        out["setup_status"] = self._setup_status()
        out["joined"] = membership.first_run_state() == "joined"
        out["join_relay"] = 1
        out.update(join_job.relay_request() or {})
        return out

    async def _join(self, req: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        fields = {k: req.get(k) for k in ("code", "link", "candidate_fid", "totp")}
        if any(v is not None and not isinstance(v, str) for v in fields.values()):
            yield {"error": "bad_request"}
            return
        totp = fields["totp"]
        totp_ok = False
        if totp is not None:
            totp_ok = await self._totp_ok(totp)
            if not totp_ok:
                log.info("door_join_refused", reason="bad_totp")
                yield {"error": "bad_totp"}
                return
        try:
            job = membership.start_join(fields["code"], fields["link"], fields["candidate_fid"], origin="door", totp_ok=totp_ok)
        except join_job.JoinNotAllowed as exc:
            yield {"error": exc.code}
            return
        yield job.status()

    def _relay_path_ok(self, path: Any) -> bool:
        if not isinstance(path, str) or os.path.dirname(path) != os.path.dirname(self.path) or not RELAY_NAME.fullmatch(os.path.basename(path)):
            return False
        try:
            st = os.lstat(path)
        except OSError:
            return False
        return stat.S_ISSOCK(st.st_mode) and st.st_uid == self._uid

    async def _relay(self, req: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        address, fid = req.get("address"), req.get("expect_fid")
        if (not self._relay_path_ok(req.get("relay")) or not isinstance(address, str) or not RELAY_ADDRESS.fullmatch(address)
                or not (fid is None or (isinstance(fid, str) and RELAY_FID.fullmatch(fid))) or not isinstance(req.get("job"), str)):
            yield {"error": "bad_request"}
            return
        try:
            job = await join_job.attach_relay(req["relay"], address, fid, req["job"])
        except join_job.JoinNotAllowed as exc:
            yield {"error": exc.code}
            return
        last = job.status()
        yield last
        while job.running:
            await asyncio.sleep(STREAM_POLL_S)
            now = job.status()
            if now != last:
                last = now
                yield now
        if job.status() != last:
            yield job.status()

    def _relay_fail(self, req: Dict[str, Any]) -> Dict[str, Any]:
        """The ``relay_fail`` op: the helper could not reach main. Answers the job's status or an error document."""
        cands = req.get("candidates")
        code = req.get("code")
        if not isinstance(code, str) or not (cands is None or isinstance(cands, list)) or not isinstance(req.get("job"), str):
            return {"error": "bad_request"}
        try:
            return join_job.fail_relay(code, cands, req["job"]).status()
        except join_job.JoinNotAllowed as exc:
            return {"error": exc.code}

    async def _do_login(self) -> Dict[str, Any]:
        if membership.first_run_state() != "joined":
            return {"error": "not_joined"}
        try:
            tokens = await self._login(self._refresh_store())
        except RuntimeError:
            return {"error": "login_failed"}
        log.info("door_login")
        return tokens

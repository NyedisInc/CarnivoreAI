
from __future__ import annotations

import asyncio
import secrets
import ssl
import uuid
from contextlib import closing
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.computers import commit, join_identity, join_proto, store
from src.core.computers.commit import JoinRefused, PackSettingsPort, PeerId, PinListener
from src.core.computers.invites import Invite, Invites
from src.core.computers.join_limits import PRE_PER_SOURCE, PRE_TOTAL, Rates, Slots
from src.core.computers.link_listener import _HandshakeGate, _TlsGate
from src.core.computers.join_proto import JoinKeys, JoinPake, ProtoError
from src.core.computers.tls_identity import CertRejected, LinkIdentity, server_join_ctx, validate_peer_cert
from src.core.relay_identity.device_key import DeviceKey

log = structlog.get_logger(__name__)


class JoinServer:

    def __init__(self, *, invites: Invites, identity: LinkIdentity, fed_key: DeviceKey, public_key: str, own_iid: str, own_label: str,
                 open_db: commit.OpenDb, listener: PinListener, pack: PackSettingsPort, host: str = "0.0.0.0", port: int = 0,
                 addresses: Callable[[], Sequence[str]] = lambda: (), link_port: int = 0, app_version: str = "",
                 is_member: Callable[[], bool] = lambda: False, notify: Optional[commit.Notify] = None, fail_delay: float = 1.0,
                 rates: Optional[Rates] = None, on_member: Optional[Callable[[str], None]] = None, lan_only: bool = True) -> None:
        self._inv, self._ident, self._key, self._pub = invites, identity, fed_key, public_key
        self._iid, self._label, self._open_db, self._listener, self._pack = own_iid, own_label, open_db, listener, pack
        self._host, self._want_port, self._addresses, self._link_port = host, port, addresses, link_port
        self._app_version, self._is_member, self._notify, self._delay = app_version, is_member, notify, fail_delay
        self._on_member, self._lan_only = on_member, lan_only
        self._slots, self._rates = Slots(), rates or Rates()
        self._server: Optional[asyncio.AbstractServer] = None
        self._session_busy = False
        self._ctx: Optional[ssl.SSLContext] = None
        self._gate = _HandshakeGate(PRE_PER_SOURCE, PRE_TOTAL)
        self._sync_lock = asyncio.Lock()

    def use_key(self, fed_key: DeviceKey, public_key: str) -> None:
        self._key, self._pub = fed_key, public_key

    @property
    def port(self) -> Optional[int]:
        if self._server is None or not self._server.sockets:
            return None
        return self._server.sockets[0].getsockname()[1]

    async def sync(self) -> bool:
        async with self._sync_lock:
            if self._is_member() or not self._inv.any_live():
                await self.stop()
                return False
            if self._server is None:
                self._ctx = server_join_ctx(self._ident)
                loop = asyncio.get_running_loop()
                self._server = await _TlsGate.open(self, loop, self._host, self._want_port)
                log.info("computer_join_port_open", port=self.port)
            return True

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()
            log.info("computer_join_port_closed")

    async def _on_tls_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await self._on_connect(reader, writer)

    async def _on_connect(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        addr = peer[0] if peer else "?"
        try:
            await self._serve(reader, writer, addr)
        except (ProtoError, asyncio.TimeoutError, ConnectionError, ssl.SSLError, OSError) as exc:
            log.info("computer_join_dropped", reason=type(exc).__name__)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("computer_join_failed", error=type(exc).__name__)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, ssl.SSLError, OSError):
                pass

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, addr: str) -> None:
        if self._is_member() or not self._slots.enter(addr):
            return
        try:
            async def first() -> Dict[str, Any]:
                await join_proto.read_magic(reader, join_proto.FIRST_MESSAGE_TIMEOUT)
                return await join_proto.read_message(reader, join_proto.FIRST_MESSAGE_TIMEOUT)

            hello = join_proto.check_hello(await asyncio.wait_for(first(), join_proto.FIRST_MESSAGE_TIMEOUT))
        except join_proto.Incompatible:
            log.info("computer_join_incompatible")
            await self._refuse(writer, "incompatible")
            return
        finally:
            self._slots.leave(addr)
        if self._session_busy:
            await self._refuse(writer, "busy")
            return
        if not self._rates.admit(addr):
            await self._refuse(writer, "rate_limited")
            return
        inv = self._inv.take_attempt(hello["mode"], hello["invite_id"])
        if inv is None:
            await self._refuse(writer, "no_invite")
            return
        self._session_busy = True
        state = {"resolved": False}
        try:
            await asyncio.wait_for(self._session(reader, writer, addr, inv, hello, state), join_proto.SESSION_TIMEOUT)
        finally:
            self._session_busy = False
            if not state["resolved"]:
                self._inv.finish_attempt(inv, ok=False, mode=hello["mode"], addr=addr)

    async def _refuse(self, writer: asyncio.StreamWriter, code: str, left: Optional[int] = None) -> None:
        await asyncio.sleep(self._delay)
        try:
            await join_proto.write_message(writer, join_proto.error(code, left))
        except (ConnectionError, ssl.SSLError, OSError):
            pass

    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, addr: str, inv: Invite,
                       hello: Dict[str, Any], state: Dict[str, bool]) -> None:
        mode = hello["mode"]
        pake = JoinPake("main", join_proto.password(mode, code=inv.code, secret=inv.secret))
        msg_b = pake.start()
        try:
            shared = pake.finish(hello["msg_a"])
        except ProtoError:
            await self._wrong(writer, inv, mode, addr, state)
            return
        join_id = secrets.token_hex(8)
        fps = join_proto.fp_server(self._ident.cert.der)
        t = join_proto.transcript(mode=mode, invite_id=hello["invite_id"] or "", msg_a=hello["msg_a"], msg_b=msg_b, join_id=join_id,
                                  fps=fps, joiner_fid=hello["fid"])
        keys = JoinKeys(shared, t)
        await join_proto.write_message(writer, join_proto.spake(msg_b=msg_b, join_id=join_id))
        confirm = join_proto.check_confirm(await join_proto.read_message(reader, join_proto.MESSAGE_TIMEOUT), from_main=False)
        if not keys.equal(confirm["mac"], keys.mac_j()):
            await self._wrong(writer, inv, mode, addr, state)
            return
        main_obj = {"install_id": self._iid, "fid": self._key.device_id}
        await join_proto.write_message(writer, join_proto.confirm_m(main_obj, keys.mac_m(main_obj)))
        try:
            await self._after_proof(reader, writer, addr, inv, hello, state, t, keys)
        except (JoinRefused, ProtoError) as exc:
            log.info("computer_join_refused", reason=getattr(exc, "code", "protocol"))
            self._inv.refund_attempt(inv)
            state["resolved"] = True
            await self._refuse(writer, "refused")
        except BaseException:
            self._inv.refund_attempt(inv)
            state["resolved"] = True
            raise

    async def _wrong(self, writer: asyncio.StreamWriter, inv: Invite, mode: str, addr: str, state: Dict[str, bool]) -> None:
        left = self._inv.finish_attempt(inv, ok=False, mode=mode, addr=addr)
        state["resolved"] = True
        await self._refuse(writer, "wrong_code", left)

    async def _after_proof(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, addr: str, inv: Invite,
                           hello: Dict[str, Any], state: Dict[str, bool], t: bytes, keys: JoinKeys) -> None:
        msg = await join_proto.read_message(reader, join_proto.MESSAGE_TIMEOUT)
        if msg.get("t") == "abort":
            code = msg.get("code")
            log.info("computer_join_joiner_aborted", reason=code if code in join_proto.ABORT_CODES else "unknown")
            self._inv.refund_attempt(inv)
            state["resolved"] = True
            return
        body, cert_der = join_identity.verify_identity(msg, t=t, keys=keys, sender_role="J")
        if body["fid"] != hello["fid"] or body["install_id"] == self._iid:
            raise JoinRefused("refused", "joiner identity mismatch")
        existing = body.get("existing_grant_id")
        if existing is not None and (not isinstance(existing, str) or len(existing) > 64):
            raise ProtoError("existing grant id malformed")
        try:
            cert = validate_peer_cert(cert_der, own_link_fid=self._ident.cert.link_fid)
        except CertRejected as exc:
            raise JoinRefused("refused", str(exc)) from None
        joiner = PeerId(body["install_id"], body["label"], body["public_key"], cert_der, cert.link_fid, body["grant_id"])
        member_addresses, member_port = self._member_listen(body, addr)
        kind = await asyncio.to_thread(self._classify, joiner)
        result = await commit.main_provisional(self._open_db, self._listener, identity=self._ident, own_iid=self._iid, joiner=joiner,
                                               kind=kind, pack=self._pack, announced_grant_id=uuid.uuid4().hex, notify=self._notify,
                                               member_addresses=member_addresses, member_port=member_port)
        self._tell_member(joiner.install_id)
        self._inv.finish_attempt(inv, ok=True, mode=hello["mode"], addr=addr)
        state["resolved"] = True
        reply = join_identity.build_identity(
            role="M", t=t, keys=keys, key=self._key, install_id=self._iid, label=self._label, public_key=self._pub,
            cert_der=self._ident.cert.der, grant_id=result.grant_id, app_version=self._app_version,
            extra={"link_port": self._link_port, "addresses": list(self._addresses()), "settings": result.settings})
        await join_proto.write_message(writer, reply)
        try:
            final = await join_proto.read_message(reader, join_proto.MESSAGE_TIMEOUT)
            if final.get("t") == "done":
                log.info("computer_join_provisional_acked", iid=joiner.install_id[:8], kind=kind)
                self._tell_member(joiner.install_id)
        except (ProtoError, asyncio.TimeoutError, ConnectionError, ssl.SSLError, OSError):
            log.info("computer_join_no_ack", iid=joiner.install_id[:8])

    def _member_listen(self, body: Dict[str, Any], observed: str) -> Tuple[List[str], int]:
        addresses, port = join_identity.listen_of(body, join_port=self.port or 0, lan_only=self._lan_only)
        if observed not in addresses and join_identity.lan_address_ok(observed, lan_only=self._lan_only):
            names = sum(1 for a in addresses if a.lower().endswith(".local"))
            addresses.insert(names, observed)
        return addresses, port

    def _tell_member(self, iid: str) -> None:
        if self._on_member is not None:
            try:
                self._on_member(iid)
            except Exception as exc:  # noqa: BLE001
                log.warning("computer_join_member_hint_failed", error_type=type(exc).__name__)

    def _classify(self, joiner: PeerId) -> str:
        with closing(self._open_db()) as conn:
            for row in store.list_rows(conn):
                if row.link_fid == joiner.link_fid and row.peer_install_id != joiner.install_id:
                    raise JoinRefused("refused", "that link identity belongs to another computer")
            return commit.classify_join(conn, own_iid=self._iid, own_link_fid=self._ident.cert.link_fid, joiner=joiner)


from __future__ import annotations

import asyncio
import json
import re
import ssl
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, Union

import structlog

from src.core.computers.link_listener import ALERTED, LINKED, NO_HELLO
from src.core.computers.mux import frames as mf
from src.core.computers.mux.session import MuxError, MuxSession, MuxStream
from src.core.federation.pairing import PROTOCOL_MAJOR
from src.core.pack.machines import roster_v2
from src.core.pack.machines.roster_v2 import RosterV2

log = structlog.get_logger(__name__)

MESH_ALPN = "carnivore-mesh/1"
LIST_SERVICE = "mesh-list"
PEER_API = "peer-api"
HELLO_TIMEOUT = 5.0
SUMMARY_MAX = 512
LIST_READ_TIMEOUT = 5.0
FETCH_TIMEOUT = 30.0
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

Summary = Dict[str, Any]


@dataclass
class MeshSession:

    peer: str
    dialed_by_me: bool
    started_at: float
    mux: MuxSession
    peer_summary: Optional[Summary] = None
    cert_sha: str = ""
    own_sha: str = ""
    opened_wall: float = field(default_factory=time.time)
    extra: Dict[str, Any] = field(default_factory=dict)


def summary_of(lst: Any, wire: Optional[Dict[str, Any]]) -> Optional[Summary]:
    if not isinstance(lst, RosterV2) or wire is None:
        return None
    return {"g": lst.generation, "t": lst.issued_at, "sha": roster_v2.sha(roster_v2.blob(wire))}


def valid_summary(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == {"g", "t", "sha"} and all(type(value[k]) is int and 0 <= value[k] < 2 ** 62 for k in ("g", "t"))
            and isinstance(value["sha"], str) and bool(_HEX64.match(value["sha"])))


def newer(a: Optional[Summary], b: Optional[Summary]) -> bool:
    if a is None:
        return False
    return b is None or (a["g"], a["t"]) > (b["g"], b["t"])


def build_hello(own_iid: str, summary: Optional[Summary], seen: Optional[str] = None) -> Dict[str, Any]:
    hello: Dict[str, Any] = {"v": mf.PROTOCOL_VERSION, "proto": PROTOCOL_MAJOR, "mesh": 1, "iid": own_iid, "list": summary}
    if seen is not None:
        hello["seen"] = seen
    return hello


def check_hello(hello: Dict[str, Any], pinned_iid: str) -> Optional[int]:
    if hello.get("proto") != PROTOCOL_MAJOR:
        return mf.GO_VERSION
    if hello.get("mesh") != 1 or hello.get("iid") != pinned_iid:
        return mf.GO_PROTOCOL
    if hello.get("list") is not None and not valid_summary(hello.get("list")):
        return mf.GO_PROTOCOL
    if "seen" in hello and not (isinstance(hello["seen"], str) and _HEX64.match(hello["seen"])):
        return mf.GO_PROTOCOL
    return None


def _alpn(writer: asyncio.StreamWriter) -> Optional[str]:
    ssl_obj = writer.get_extra_info("ssl_object")
    try:
        return ssl_obj.selected_alpn_protocol() if ssl_obj is not None else None
    except ValueError:
        return None


def _is_alert(err: Optional[BaseException]) -> bool:
    return isinstance(err, ssl.SSLError) and "ALERT" in str(err.reason or "").upper()


async def open_session(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, peer: str, accepting: bool, own_iid: str,
                       summary: Callable[[], Optional[Summary]], on_open: Callable[[MuxStream], Awaitable[None]],
                       already_linked: Callable[[str], bool], cert_sha: str, own_fallback: str = "") -> Union[MeshSession, str]:
    if not accepting:
        if _alpn(writer) != MESH_ALPN:
            writer.close()
            return ALERTED
        if already_linked(peer):
            writer.close()
            return LINKED
    mux = MuxSession(reader, writer, dialer=accepting, services=frozenset({LIST_SERVICE, PEER_API}), on_open=on_open)
    try:
        await mux.start(build_hello(own_iid, summary(), cert_sha))
        hello = await asyncio.wait_for(mux.hello(), HELLO_TIMEOUT)
    except asyncio.CancelledError:
        writer.close()
        raise
    except (MuxError, asyncio.TimeoutError, OSError):
        err = mux.read_error or reader.exception()
        gone = mux.goaway_reason in (mf.GO_REMOVED, mf.GO_REPLACED)
        await mux.close(mf.GO_NORMAL)
        if _is_alert(err) or gone or not accepting:
            return ALERTED
        return NO_HELLO
    bad = check_hello(hello, peer)
    if bad is not None:
        log.info("mesh_link_hello_refused", peer=peer[:8], code=bad)
        await mux.close(bad)
        return NO_HELLO
    return MeshSession(peer=peer, dialed_by_me=not accepting, started_at=time.monotonic(), mux=mux, peer_summary=hello.get("list"), cert_sha=cert_sha,
                       own_sha=hello.get("seen") or own_fallback)


async def _read_capped(stream: MuxStream, cap: int, timeout: float) -> Optional[bytes]:
    buf = bytearray()

    async def go() -> bool:
        while True:
            chunk = await stream.read(cap + 1 - len(buf))
            if not chunk:
                return True
            buf.extend(chunk)
            if len(buf) > cap:
                return False

    try:
        return bytes(buf) if await asyncio.wait_for(go(), timeout) else None
    except asyncio.TimeoutError:
        return None


async def serve_list(stream: MuxStream, held: Callable[[], Optional[Tuple[Summary, bytes]]]) -> Optional[Summary]:
    try:
        raw = await _read_capped(stream, SUMMARY_MAX, LIST_READ_TIMEOUT)
        try:
            theirs = json.loads(raw) if raw is not None else None
        except ValueError:
            theirs = None
        if not valid_summary(theirs):
            stream.reset(mf.RST_LIMIT if raw is None else mf.RST_ERROR)
            return None
        mine = held()
        if mine is not None and newer(mine[0], theirs):
            await stream.write(mine[1])
        stream.close()
        return theirs
    except MuxError:
        return None


async def fetch_list(mux: MuxSession, summary: Optional[Summary]) -> Optional[Dict[str, Any]]:
    stream = await mux.open(LIST_SERVICE)
    try:
        await stream.write(json.dumps(summary if summary is not None else {"g": 0, "t": 0, "sha": "0" * 64}, separators=(",", ":")).encode())
        stream.close()
        raw = await _read_capped(stream, roster_v2.MAX_BLOB_BYTES, FETCH_TIMEOUT)
    except (MuxError, asyncio.TimeoutError):
        stream.reset(mf.RST_ERROR)
        raise
    if raw is None:
        stream.reset(mf.RST_LIMIT)
        return None
    if not raw:
        return None
    try:
        doc = json.loads(raw)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None

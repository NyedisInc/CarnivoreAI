
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import secrets
import socket
import stat
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.federation.pair_socket import peer_uid

log = structlog.get_logger(__name__)

DISCOVERY_WAIT_SECONDS = 6.0
DISCOVERY_POLL_SECONDS = 0.25
CONNECT_TIMEOUT = 5.0
ACCEPT_TIMEOUT = 10.0
PUMP_TIMEOUT = 60.0
DOOR_TIMEOUT = 10.0
CHUNK = 64 * 1024
_SAFE = re.compile(r"[^A-Za-z0-9 ._-]")
_DOOR_NAME = re.compile(r"^door-[0-9a-f]{8}\.sock$")
STALE_RELAY_SECONDS = 30.0
_door_override: Optional[str] = None

Main = Dict[str, Any]


def fed_dir() -> Path:
    return Path.home() / ".carnivore" / "fed"


def door_path_ok(path: str) -> bool:
    return isinstance(path, str) and os.path.dirname(path) == str(fed_dir()) and bool(_DOOR_NAME.fullmatch(os.path.basename(path)))


def door_path() -> str:
    if _door_override is not None:
        return _door_override
    from src.core.hosts.ssh_master import default_instance_tag

    return str(fed_dir() / f"door-{default_instance_tag()}.sock")


MAX_CANDIDATES = 16
_CAND_FIELD_MAX = {"name": 64, "fid": 64, "fid_short": 8, "pack_name": 32}

def _clean(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return _SAFE.sub("", str(value))[:64]


async def ask_door(request: Dict[str, Any], *, stream: bool = False, path: Optional[str] = None):
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(path or door_path()), DOOR_TIMEOUT)
    try:
        writer.write(json.dumps(request).encode() + b"\n")
        await writer.drain()
        while True:
            raw = await (reader.readline() if stream else asyncio.wait_for(reader.readline(), DOOR_TIMEOUT))
            if not raw:
                return
            with contextlib.suppress(ValueError):
                doc = json.loads(raw)
                if isinstance(doc, dict):
                    yield doc
                    if not stream:
                        return
    finally:
        writer.close()


async def ask_once(request: Dict[str, Any]) -> Dict[str, Any]:
    try:
        async for doc in ask_door(request):
            return doc
    except (OSError, asyncio.TimeoutError):
        pass
    return {"error": "door_unreachable"}


async def ask_held() -> Tuple[Dict[str, Any], Optional["asyncio.StreamWriter"]]:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(door_path()), DOOR_TIMEOUT)
    except (OSError, asyncio.TimeoutError):
        return {"error": "door_unreachable"}, None
    try:
        writer.write(json.dumps({"op": "status", "hold": True}).encode() + b"\n")
        await writer.drain()
        doc = json.loads(await asyncio.wait_for(reader.readline(), DOOR_TIMEOUT))
        if isinstance(doc, dict):
            return doc, writer
    except (OSError, asyncio.TimeoutError, ValueError):
        pass
    writer.close()
    return {"error": "door_unreachable"}, None


async def find_targets(status: Dict[str, Any]) -> List[Main]:
    if status.get("mode") == "link":
        return [{"name": None, "fid": None, "fid_short": None, "addresses": [(str(h), int(p)) for h, p in status.get("targets") or []]}]
    from src.config import settings
    from src.core.federation import discovery

    disc = discovery.Discovery(config_path=Path(settings.auth_config_file).expanduser(), advertise_allowed=False)
    disc.start(asyncio.get_running_loop())
    try:
        want, deadline, look = status.get("candidate_fid"), time.monotonic() + DISCOVERY_WAIT_SECONDS, status.get("mode") == "look"
        while True:
            cands = [c for c in disc.candidates() if want is None or c["fid"] == want]
            expired = time.monotonic() >= deadline
            if expired or not look:
                answered = await discovery.probe_join_ports(cands) if cands else []
                if answered or expired:
                    break
            await asyncio.sleep(DISCOVERY_POLL_SECONDS)
    finally:
        disc.stop()
    return [{"name": c["name"], "fid": c["fid"], "fid_short": c["fid_short"], "pack_name": c.get("pack_name"), "addresses": [(c["join_address"], int(c["lp"]) + 1)]}
            for c in answered]


async def connect_first(addresses: Sequence[Tuple[str, int]]) -> Tuple[str, "asyncio.StreamReader", "asyncio.StreamWriter"]:
    async def one(host: str, port: int):
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), CONNECT_TIMEOUT)
        return host, reader, writer

    pending = {asyncio.ensure_future(one(h, p)) for h, p in addresses}
    winner, last = None, OSError("no address")
    try:
        while pending and winner is None:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                exc = t.exception()
                if exc is not None:
                    last = exc if isinstance(exc, OSError) else OSError(type(exc).__name__)
                elif winner is None:
                    winner = t.result()
                else:
                    t.result()[2].close()
    finally:
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    if winner is None:
        raise last
    return winner


def _remove_stale_relays(directory: Path) -> None:
    for entry in directory.glob("relay-*.sock"):
        try:
            info = os.lstat(entry)
            if stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid() and time.time() - info.st_mtime > STALE_RELAY_SECONDS:
                os.unlink(entry)
                log.info("join_helper_stale_relay_removed")
        except OSError as exc:
            log.info("join_helper_stale_relay_skipped", error_type=type(exc).__name__)


def bind_relay(directory: Path) -> Tuple[socket.socket, str]:
    _remove_stale_relays(directory)
    path = str(directory / f"relay-{secrets.token_hex(8)}.sock")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        sock.bind(path)
    except OSError:
        sock.close()
        raise
    finally:
        os.umask(old)
    os.chmod(path, 0o600)
    sock.listen(1)
    sock.setblocking(False)
    return sock, path


async def accept_one(sock: socket.socket) -> Optional[socket.socket]:
    loop, deadline = asyncio.get_running_loop(), time.monotonic() + ACCEPT_TIMEOUT
    while (left := deadline - time.monotonic()) > 0:
        try:
            conn, _ = await asyncio.wait_for(loop.sock_accept(sock), left)
        except asyncio.TimeoutError:
            return None
        if peer_uid(conn) == os.getuid():
            return conn
        log.warning("join_helper_relay_foreign_peer")
        conn.close()
    return None


async def _copy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(CHUNK):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        with contextlib.suppress(OSError, RuntimeError):
            if writer.can_write_eof():
                writer.write_eof()


async def pump(a: Tuple[asyncio.StreamReader, asyncio.StreamWriter], b: Tuple[asyncio.StreamReader, asyncio.StreamWriter]) -> None:
    try:
        await asyncio.wait_for(asyncio.gather(_copy(a[0], b[1]), _copy(b[0], a[1])), PUMP_TIMEOUT)
    except asyncio.TimeoutError:
        log.info("join_helper_pump_timeout")
    finally:
        for w in (a[1], b[1]):
            w.close()


class Printer:

    def __init__(self, *, machine: bool, agent: bool) -> None:
        self.machine, self.agent = machine, agent

    def step(self, name: str, person: str = "") -> None:
        if self.machine:
            if not self.agent or name in ("connect", "join"):
                print(f"step={_clean(name)}", flush=True)
        elif person:
            print(person, flush=True)

    def final(self, doc: Dict[str, Any]) -> None:
        state = doc.get("state") or "failed"
        error = doc.get("error")
        if self.machine:
            print(f"state={_clean(state)}", flush=True)
            for key in ("error", "main_label", "main_iid", "tries_left"):
                if doc.get(key) is not None:
                    print(f"{key}={_clean(doc[key])}", flush=True)
            for cand in doc.get("candidates") or []:
                if isinstance(cand, dict):
                    print("candidate=" + "|".join(_clean(cand.get(k, "")) for k in ("fid", "fid_short", "name")), flush=True)
        elif state == "joined":
            print(f"joined {_clean(doc.get('main_label') or 'your main computer')}'s pack. you can close this window.", flush=True)
        elif state == "finding":
            print("found a pack on this network. go back to the carnivore window.", flush=True)
        else:
            print(f"the join did not finish: {_clean(error or 'failed')}", flush=True)


async def serve(out: Printer, *, first_request: Optional[Dict[str, Any]]) -> int:
    if first_request is not None:
        doc = await ask_once(first_request)
        if doc.get("state") != "waiting_relay":
            out.final(doc)
            return 0
    status, hold = await ask_held()
    try:
        if status.get("state") != "waiting_relay" or not isinstance(status.get("job"), str):
            out.final(status if "state" in status else {"state": "failed", "error": status.get("error") or "no_join_waiting"})
            return 0
        return await _serve_waiting(out, status)
    finally:
        if hold is not None:
            hold.close()


async def _relay_failed(job: str, code: str, **extra: Any) -> Dict[str, Any]:
    doc = await ask_once({"op": "relay_fail", "job": job, "code": code, **extra})
    if doc.get("error") or "state" not in doc:
        return {"state": "failed", "error": code}
    return doc


async def _serve_waiting(out: Printer, status: Dict[str, Any]) -> int:
    job = status["job"]
    out.step("finding_pack", "finding your pack")
    from src.core.federation import discovery

    look = status.get("mode") == "look"
    try:
        mains = await find_targets(status)
    except discovery.LocalNetworkBlocked:
        out.final(await _relay_failed(job, "local_network_blocked"))
        return 0
    except OSError as exc:  # could not
        log.info("join_helper_discovery_failed", error_type=type(exc).__name__)
        mains = []
    if look or len(mains) != 1 or not mains[0]["addresses"]:
        code = ("found" if mains else "no_pack") if look else "several" if len(mains) > 1 else "no_pack"
        cands = [{k: (None if m.get(k) is None else str(m[k])[:n]) for k, n in _CAND_FIELD_MAX.items()}
                 for m in mains[:MAX_CANDIDATES]] if code in ("several", "found") else None
        out.final(await _relay_failed(job, code, **({"candidates": cands} if cands else {})))
        return 0
    main = mains[0]
    out.step("connect")
    try:
        address, tcp_r, tcp_w = await connect_first(main["addresses"])
    except OSError:
        out.final(await _relay_failed(job, "unreachable"))
        return 0
    return await _relay(out, job, main, address, (tcp_r, tcp_w))


async def _relay(out: Printer, job: str, main: Main, address: str, tcp: Tuple[asyncio.StreamReader, asyncio.StreamWriter]) -> int:
    path = None
    try:
        sock, path = bind_relay(Path(door_path()).parent)
        with contextlib.closing(sock):
            watch = asyncio.ensure_future(_watch(out, job, main, address, path))
            conn = await accept_one(sock)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(path)
            if conn is None:
                tcp[1].close()
                watch.cancel()
                out.final(await ask_once({"op": "status"}))
                return 0
            out.step("connecting", f"connecting to {_clean(main.get('name') or 'your main computer')}")
            out.step("join")
            relay = await asyncio.open_connection(sock=conn)
            await pump(tcp, relay)
            final = await watch
    finally:
        if path is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(path)
        tcp[1].close()
    out.final(final)
    return 0


async def _watch(out: Printer, job: str, main: Main, address: str, path: str) -> Dict[str, Any]:
    last: Dict[str, Any] = {"state": "failed", "error": "door_unreachable"}
    request = {"op": "relay", "job": job, "relay": path, "address": address, "expect_fid": main.get("fid")}
    try:
        async for doc in ask_door(request, stream=True):
            last = doc if "state" in doc else {"state": "failed", "error": doc.get("error") or "failed"}
            if last["state"] == "joined":
                out.step("linking", "linking")
    except (OSError, asyncio.TimeoutError):
        pass
    return last


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="join_helper", add_help=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--join", action="store_true")
    group.add_argument("--attach", action="store_true")
    parser.add_argument("--agent", action="store_true")
    parser.add_argument("--door", default=None)
    try:
        args = parser.parse_args(list(argv))
    except SystemExit:
        return 2
    global _door_override
    if args.door is not None:
        if not door_path_ok(args.door):
            return 2
        _door_override = args.door
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))
    request: Optional[Dict[str, Any]] = None
    if args.join:
        try:
            request = json.loads(sys.stdin.readline())
        except ValueError:
            return 2
        if not isinstance(request, dict) or request.get("op") != "join":
            return 2
    out = Printer(machine=args.join, agent=args.agent)
    return asyncio.run(serve(out, first_request=request))

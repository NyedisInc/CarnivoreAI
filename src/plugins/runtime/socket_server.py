
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import re
import socket
import stat
import struct
import sys
from pathlib import Path
from typing import Callable, Dict, Optional, Set

import structlog

from src.plugins.runtime import frames, guards
from src.plugins.runtime.dispatch import HostDispatcher, PluginContext

logger = structlog.get_logger()

SOCKET_PATH_MAX = 103
SOCKET_DIR_NAME = "plugin-sockets"
FALLBACK_ROOT = "/tmp"
_SAFE_KEY = re.compile(r"[^A-Za-z0-9._-]+")


def peer_uid(sock: socket.socket) -> Optional[int]:
    try:
        if sys.platform == "darwin":
            raw = sock.getsockopt(0, 0x001, 76)
            return struct.unpack_from("II", raw)[1]
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))  # type: ignore[attr-defined]
        return struct.unpack("3i", raw)[1]
    except (OSError, struct.error):
        return None


def _user_temp_dir() -> Optional[str]:
    try:
        return os.confstr("CS_DARWIN_USER_TEMP_DIR") or None
    except (AttributeError, ValueError, OSError):
        return None


def _is_private_dir(path: Path, expected_uid: Optional[int] = None) -> bool:
    uid = os.getuid() if expected_uid is None else expected_uid
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_uid == uid and not (stat.S_IMODE(st.st_mode) & 0o077)


def _ensure_private_dir(path: Path, *, owner_uid: Optional[int] = None) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if owner_uid is not None and owner_uid != os.getuid():
        os.chown(path, owner_uid, owner_uid)
    os.chmod(path, 0o700)
    real = Path(os.path.realpath(path))
    if not _is_private_dir(real, expected_uid=owner_uid):
        raise OSError(f"socket directory {real} is not a private 0700 directory owned by expected user")
    return real


def socket_path_for(state_dir: Path, install_key: str, *, dir_owner_uid: Optional[int] = None) -> Path:
    safe_key = _SAFE_KEY.sub("_", install_key or "plugin")[:48] or "plugin"
    state_real = Path(os.path.realpath(state_dir))
    primary_dir = _ensure_private_dir(state_real / SOCKET_DIR_NAME, owner_uid=dir_owner_uid)
    primary = primary_dir / f"{safe_key}.sock"
    if len(os.fsencode(str(primary))) <= SOCKET_PATH_MAX:
        return primary

    state_tag = hashlib.sha256(str(state_real).encode("utf-8", errors="replace")).hexdigest()[:10]
    key_tag = hashlib.sha256(install_key.encode("utf-8", errors="replace")).hexdigest()[:10]
    short_name = f"ps-{state_tag}-{key_tag}.sock"

    user_tmp = _user_temp_dir()
    if user_tmp is not None:
        tmp_real = Path(os.path.realpath(user_tmp))
        if _is_private_dir(tmp_real, expected_uid=dir_owner_uid):
            cand = tmp_real / short_name
            if len(os.fsencode(str(cand))) <= SOCKET_PATH_MAX:
                return cand

    fb_uid = os.getuid() if dir_owner_uid is None else dir_owner_uid
    fallback_dir = _ensure_private_dir(
        Path(os.path.realpath(FALLBACK_ROOT)) / f"carnivore-psock-{fb_uid}",
        owner_uid=dir_owner_uid,
    )
    cand = fallback_dir / short_name
    if len(os.fsencode(str(cand))) > SOCKET_PATH_MAX:
        raise OSError("resolved socket path exceeds AF_UNIX sun_path limit")
    return cand


class PluginSocketServer:

    def __init__(
        self,
        ctx: PluginContext,
        dispatcher: HostDispatcher,
        sock_path: Path,
        is_active: Optional[Callable[[], bool]] = None,
        allowed_peer_uid: Optional[int] = None,
    ) -> None:
        self._ctx = ctx
        self._dispatcher = dispatcher
        self._sock_path = Path(sock_path)
        self._is_active = is_active or (lambda: True)
        self._allowed_peer_uid = os.getuid() if allowed_peer_uid is None else allowed_peer_uid
        self._server: Optional[asyncio.AbstractServer] = None
        self._clients: Set[asyncio.Task] = set()
        self._stopped = False

    @property
    def path(self) -> Path:
        return self._sock_path

    async def start(self) -> Path:
        owner_uid = self._allowed_peer_uid if self._allowed_peer_uid != os.getuid() else None
        parent = _ensure_private_dir(self._sock_path.parent, owner_uid=owner_uid)
        target = parent / self._sock_path.name
        try:
            st = os.lstat(target)
        except FileNotFoundError:
            st = None
        if st is not None:
            if not stat.S_ISSOCK(st.st_mode):
                raise OSError(f"refusing to unlink non-socket path at {target}")
            os.unlink(target)
        self._server = await asyncio.start_unix_server(self._on_connect, path=str(target))
        if owner_uid is not None:
            os.chown(target, owner_uid, owner_uid)
        os.chmod(target, 0o600)
        self._sock_path = Path(os.path.realpath(target))
        self._stopped = False
        return self._sock_path

    async def stop(self) -> None:
        self._stopped = True
        server, self._server = self._server, None
        if server is not None:
            server.close()
            with contextlib.suppress(OSError):
                await server.wait_closed()
        for task in list(self._clients):
            task.cancel()
        if self._clients:
            await asyncio.gather(*self._clients, return_exceptions=True)
        self._clients.clear()
        with contextlib.suppress(FileNotFoundError, OSError):
            st = os.lstat(self._sock_path)
            if stat.S_ISSOCK(st.st_mode):
                os.unlink(self._sock_path)

    async def _on_connect(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._clients.add(task)
        try:
            await self._serve_client(reader, writer)
        finally:
            if task is not None:
                self._clients.discard(task)

    async def _serve_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            sock = writer.get_extra_info("socket")
            if sock is None or peer_uid(sock) != self._allowed_peer_uid:
                logger.warning("cplug_sock_refused_uid", cplug=self._ctx.plugin_id)
                return
            if self._stopped or not self._is_active():
                return
            splitter = frames.LineSplitter()
            guard = frames.FrameGuard()
            while not self._stopped and self._is_active():
                chunk = await reader.read(65536)
                if not chunk:
                    return
                for line in splitter.feed(chunk):
                    frame = guard.parse(line)
                    if frame.kind == "response":
                        raise frames.FrameViolation("unsolicited_response", "client cannot send response")
                    if frame.kind == "notification":
                        if frame.method == "log" and isinstance(frame.params, dict):
                            with contextlib.suppress(guards.Refused):
                                await self._dispatcher.handle(self._ctx, "log", frame.params, source="cli_sock")
                        continue
                    try:
                        outcome = await self._dispatcher.handle(self._ctx, frame.method or "", frame.params, source="cli_sock")
                    except guards.Refused as refusal:
                        outcome = refusal
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("cplug_sock_service_error", cplug=self._ctx.plugin_id, method=frame.method, error_type=type(exc).__name__)
                        self._dispatcher.record(self._ctx, frame.method or "", "internal_error", type(exc).__name__)
                        outcome = guards.Refused("internal_error", type(exc).__name__)
                    finally:
                        guard.request_done()
                    writer.write(self._dispatcher.reply(frame.id or 0, outcome))
                    await writer.drain()
        except frames.FrameViolation as exc:
            logger.warning("cplug_sock_frame_violation", cplug=self._ctx.plugin_id, code=exc.code)
            with contextlib.suppress(OSError, ConnectionError):
                writer.write(frames.error_reply(1, frames.INVALID_REQUEST, exc.code))
                await writer.drain()
        except (ConnectionError, OSError, asyncio.CancelledError):
            return
        finally:
            with contextlib.suppress(OSError):
                writer.close()


class PluginSocketManager:

    def __init__(self) -> None:
        self._servers: Dict[str, PluginSocketServer] = {}

    @staticmethod
    def sweep_stale(state_dir: Path) -> int:
        removed = 0
        state_real = Path(os.path.realpath(state_dir))
        state_tag = hashlib.sha256(str(state_real).encode("utf-8", errors="replace")).hexdigest()[:10]
        dirs = [state_real / SOCKET_DIR_NAME]
        user_tmp = _user_temp_dir()
        if user_tmp is not None:
            dirs.append(Path(os.path.realpath(user_tmp)))
        dirs.append(Path(os.path.realpath(FALLBACK_ROOT)) / f"carnivore-psock-{os.getuid()}")
        for folder in dirs:
            if not folder.is_dir():
                continue
            pattern = "*.sock" if folder.name == SOCKET_DIR_NAME else f"ps-{state_tag}-*.sock"
            for item in folder.glob(pattern):
                with contextlib.suppress(OSError):
                    if stat.S_ISSOCK(os.lstat(item).st_mode):
                        os.unlink(item)
                        removed += 1
        return removed

    def path_for(self, plugin_id: str) -> Optional[Path]:
        srv = self._servers.get(plugin_id)
        return srv.path if srv is not None else None

    async def ensure(
        self,
        state_dir: Path,
        ctx: PluginContext,
        dispatcher: HostDispatcher,
        is_active: Optional[Callable[[], bool]] = None,
        allowed_peer_uid: Optional[int] = None,
    ) -> Path:
        old = self._servers.pop(ctx.plugin_id, None)
        if old is not None:
            await old.stop()
        dir_owner_uid = allowed_peer_uid if allowed_peer_uid is not None and allowed_peer_uid != os.getuid() else None
        sock_path = socket_path_for(state_dir, ctx.install_key, dir_owner_uid=dir_owner_uid)
        srv = PluginSocketServer(ctx, dispatcher, sock_path, is_active=is_active, allowed_peer_uid=allowed_peer_uid)
        real_path = await srv.start()
        self._servers[ctx.plugin_id] = srv
        return real_path

    async def stop(self, plugin_id: str) -> None:
        srv = self._servers.pop(plugin_id, None)
        if srv is not None:
            await srv.stop()

    async def stop_all(self) -> None:
        for pid in list(self._servers):
            await self.stop(pid)

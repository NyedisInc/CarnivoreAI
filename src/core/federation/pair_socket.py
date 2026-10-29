
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import stat
import struct
import sys
from pathlib import Path
from typing import Callable, Optional

import structlog

from src.core.federation import pairing

logger = structlog.get_logger()

SOCKET_NAME_PREFIX = "pair-"


def peer_uid(sock: socket.socket) -> Optional[int]:
    try:
        if sys.platform == "darwin":
            raw = sock.getsockopt(0, 0x001, 76)
            return struct.unpack_from("II", raw)[1]
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))  # type: ignore[attr-defined]
        return struct.unpack("3i", raw)[1]
    except (OSError, struct.error):
        return None


class PairSocket:

    def __init__(self, path: str, state_dir: Path,
                 begin: Optional[Callable[[Path], str]] = None) -> None:
        self.path, self._state_dir = path, state_dir
        self._begin = begin or (lambda d: pairing.OFFERS.begin(pairing.PROOF_SSH_FILE, d).nonce)
        self._code_dir = state_dir / pairing.FILE_DIR_NAME
        self._server: Optional[asyncio.AbstractServer] = None

    async def start(self) -> None:
        directory = Path(self.path).parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
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
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.path)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            sock = writer.get_extra_info("socket")
            if sock is None or peer_uid(sock) != os.getuid():
                logger.warning("pair_socket_refused_uid")
                return
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if line.strip() != b"BEGIN":
                return
            try:
                nonce = await asyncio.to_thread(self._begin, self._state_dir)
                answer = {"nonce": nonce, "file": str(self._code_dir / f"{pairing.FILE_PREFIX}{nonce}")}
            except pairing.RateLimited:
                answer = {"error": "pair_rate_limited"}
            writer.write(json.dumps(answer).encode() + b"\n")
            await writer.drain()
        except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
            logger.info("pair_socket_io", error_type=type(exc).__name__)
        finally:
            writer.close()

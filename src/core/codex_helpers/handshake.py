
from __future__ import annotations

import json
import os
import select
import struct
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

import structlog

from src.core.codex_helpers import constants as K

logger = structlog.get_logger(__name__)

_POLL_SECONDS = 0.2


@dataclass(frozen=True)
class HandshakeResult:

    outcome: str
    elapsed_ms: int
    detail: Optional[str] = None

    @property
    def answered(self) -> bool:
        return self.outcome == K.HS_READY

    def to_dict(self) -> dict:
        return {"outcome": self.outcome, "answered": self.answered, "elapsed_ms": self.elapsed_ms, "detail": self.detail}


def hello_frame() -> bytes:
    body = json.dumps(K.HELLO_MESSAGE).encode()
    return struct.pack("<I", len(body)) + body


def judge_reply(buffer: bytes) -> Optional[str]:
    if len(buffer) < 4:
        return None if len(buffer) < K.MAX_REPLY_BYTES else K.HS_BAD_REPLY
    size = struct.unpack("<I", buffer[:4])[0]
    if size > K.MAX_REPLY_BYTES:
        return K.HS_BAD_REPLY
    if len(buffer) < 4 + size:
        return None
    try:
        message = json.loads(buffer[4:4 + size])
    except ValueError:
        return K.HS_BAD_REPLY
    return K.HS_READY if isinstance(message, dict) and message.get("type") == K.READY_TYPE else K.HS_BAD_REPLY


def _child_env() -> dict:
    return {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/")}


def _reap(proc: "subprocess.Popen[bytes]") -> None:
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=K.REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        logger.warning("codex_helper_probe_child_unreaped", pid=proc.pid)
    for stream in (proc.stdin, proc.stdout):
        if stream is not None:
            try:
                stream.close()
            except OSError as exc:
                logger.debug("codex_helper_probe_pipe_close_failed", error=str(exc))


def _await_reply(proc: "subprocess.Popen[bytes]", deadline: float) -> str:
    assert proc.stdout is not None
    buffer = b""
    while time.monotonic() < deadline:
        poller = select.poll()
        poller.register(proc.stdout.fileno(), select.POLLIN)
        ready = poller.poll(_POLL_SECONDS * 1000)
        if ready:
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                return K.HS_EXITED
            buffer += chunk
            verdict = judge_reply(buffer)
            if verdict is not None:
                return verdict
        elif proc.poll() is not None:
            return K.HS_EXITED
    return K.HS_TIMEOUT


def probe_host(host_path: str, timeout: float = K.HANDSHAKE_TIMEOUT_SECONDS) -> HandshakeResult:
    started = time.monotonic()
    try:
        proc = subprocess.Popen([host_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=_child_env(), process_group=0, close_fds=True)
    except OSError as exc:
        return HandshakeResult(K.HS_SPAWN_FAILED, 0, type(exc).__name__)
    detail: Optional[str] = None
    try:
        assert proc.stdin is not None
        try:
            proc.stdin.write(hello_frame())
            proc.stdin.flush()
        except BrokenPipeError:
            outcome = K.HS_EXITED
        else:
            outcome = _await_reply(proc, started + timeout)
    finally:
        _reap(proc)
    if outcome == K.HS_EXITED:
        detail = str(proc.returncode)
    elapsed = int((time.monotonic() - started) * 1000)
    logger.info("codex_helper_handshake", host=host_path, outcome=outcome, elapsed_ms=elapsed)
    return HandshakeResult(outcome, elapsed, detail)

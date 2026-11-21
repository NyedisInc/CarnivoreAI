
from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, Protocol, Tuple

import structlog

from src.core.tmux_transport.target import exact_pane_target

if TYPE_CHECKING:
    from src.core.tmux_backend import TmuxBackend

logger = structlog.get_logger()

RESIZE_TIMEOUT_SECONDS: float = 2.0


def script_word_needs_hex(data: bytes) -> bool:
    return b"\r" in data or b"\n" in data or data == b";"


class PaneLifecycle(Protocol):

    def spawn_env(self, env: Optional[dict]) -> Optional[dict]:
        ...

    def started(self) -> None:
        ...

    def literal_needs_hex(self, data: bytes) -> bool:
        ...

    def resize(self, cols: int, rows: int) -> None:
        ...

    def is_alive(self) -> bool:
        ...

    async def is_alive_async(self) -> bool:
        ...

    def pid(self) -> Optional[int]:
        ...

    async def resume_presence(self, uuid: str, family: Optional[str]) -> Tuple[str, str]:
        ...

    async def read_started(self) -> None:
        ...

    async def ensure_streaming(self, timeout: float) -> bool:
        ...

    async def repair_stolen_pipe(self, repair: Callable[[], Awaitable[str]]) -> str:
        ...

    async def stopping(self) -> None:
        ...

    async def stopped(self) -> None:
        ...


class LocalLifecycle:

    def __init__(self, backend: "TmuxBackend") -> None:
        self._backend = backend

    def spawn_env(self, env: Optional[dict]) -> Optional[dict]:
        return env

    def started(self) -> None:
        pass

    def literal_needs_hex(self, data: bytes) -> bool:
        return script_word_needs_hex(data)

    def resize(self, cols: int, rows: int) -> None:
        try:
            self._backend._run_tmux_sync("resize-window", "-t", exact_pane_target(self._backend.tmux_session),
                                         "-x", str(cols), "-y", str(rows), check=False,
                                         timeout=RESIZE_TIMEOUT_SECONDS)
            self._backend._run_tmux_sync("refresh-client", "-S", check=False, timeout=RESIZE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            logger.warning("tmux_resize_timeout", session=self._backend.tmux_session, cols=cols, rows=rows,
                           timeout_seconds=RESIZE_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.debug("tmux_resize_error", error=str(exc))

    def is_alive(self) -> bool:
        rc, _, _ = self._backend._run_tmux_sync(
            "has-session", "-t", f"={self._backend.tmux_session}", check=False, probe=True)
        return rc == 0

    async def is_alive_async(self) -> bool:
        return self.is_alive()

    def pid(self) -> Optional[int]:
        rc, out, _ = self._backend._run_tmux_sync(
            "display-message", "-t", exact_pane_target(self._backend.tmux_session), "-p", "#{pane_pid}",
            check=False, probe=True)
        if rc != 0:
            return None
        try:
            return int(out.decode("utf-8", errors="replace").strip())
        except ValueError:
            return None

    async def resume_presence(self, uuid: str, family: Optional[str]) -> Tuple[str, str]:
        from src.core.session_transcript_presence import family_conversation_presence

        from src.core.attention.codex_pane_home import codex_home_for_row

        presence = family_conversation_presence(
            family, uuid, working_dir=str(self._backend.working_dir),
            codex_home=codex_home_for_row(family, self._backend.socket_name, self._backend.tmux_session),
        )
        return presence.outcome, presence.detail

    async def read_started(self) -> None:
        pass

    async def ensure_streaming(self, timeout: float) -> bool:
        return True

    async def repair_stolen_pipe(self, repair: Callable[[], Awaitable[str]]) -> str:
        return await repair()

    async def stopping(self) -> None:
        pass

    async def stopped(self) -> None:
        pass

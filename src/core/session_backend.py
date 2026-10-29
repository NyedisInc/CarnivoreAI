
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import structlog

from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.tmux_discovery import (
    TMUX_AVAILABLE,
    TMUX_UNDETERMINED,
    probe_tmux,
)
from src.core.tmux_listing import TmuxListing

logger = structlog.get_logger()


class SessionBackend(ABC):

    replay_in_progress: bool = False

    tmux_session: Optional[str] = None
    socket_name: Optional[str] = None
    host_key: str = LOCAL_HOST_KEY
    _reader_task: Optional["asyncio.Task[None]"] = None
    _running: bool = False

    @property
    def is_remote(self) -> bool:
        return False

    def detach_reader(self) -> bool:
        task = self._reader_task
        cancelled = task is not None and not task.done()
        if cancelled and task is not None:
            task.cancel()
        self._reader_task = None
        self._running = False
        return cancelled

    def __init__(
        self,
        session_id: str,
        working_dir: Path,
        on_output: Optional[Callable[[bytes], Any]] = None,
    ) -> None:
        self.session_id = session_id
        self.working_dir = working_dir
        self.on_output = on_output

    @abstractmethod
    async def start(
        self,
        command: Optional[str] = None,
        env: Optional[dict] = None,
        initial_cols: Optional[int] = None,
        initial_rows: Optional[int] = None,
    ) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    @abstractmethod
    async def write(self, data: bytes) -> None:
        pass

    @abstractmethod
    async def paste_and_submit(
        self,
        text: str,
        gate: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        pass

    @abstractmethod
    def resize(self, cols: int, rows: int) -> None:
        pass

    @abstractmethod
    def is_alive(self) -> bool:
        pass

    @abstractmethod
    async def read_async(self) -> None:
        pass

    async def attach_existing(self) -> None:
        raise NotImplementedError("This backend does not support rehydration")

    @abstractmethod
    def discover_existing(self) -> TmuxListing:
        pass

    def list_attachable_sessions(
        self,
        owned_names: Optional[set] = None,
        owned_instances: Optional[set] = None,
    ) -> TmuxListing:
        return TmuxListing.answered([])

    @abstractmethod
    def capture_scrollback(self, lines: int = 3000) -> bytes:
        pass


    def pane_in_alternate_screen(self) -> bool:
        return False

    def capture_visible_screen(self) -> bytes:
        return b""


_SELECTION_LOGGED: set[tuple[str, str]] = set()


def _selected_log(socket_name: str, tmux_path: str) -> Callable[..., Any]:
    key = (str(socket_name), str(tmux_path))
    if key in _SELECTION_LOGGED:
        return logger.debug
    _SELECTION_LOGGED.add(key)
    return logger.info


def build_backend(
    settings_obj: Any,
    session_id: str,
    working_dir: Path,
    on_output: Optional[Callable[[bytes], Any]] = None,
    session_name: Optional[str] = None,
    viewer_probe: Optional[Callable[[], bool]] = None,
    socket_name_override: Optional[str] = None,
    remote_host: Optional[Any] = None,
) -> SessionBackend:
    if remote_host is not None:
        from src.core.hosts.remote_backend import make_remote_backend

        logger.info("session_backend_selected", backend="remote_tmux", host=remote_host.host_key)
        return make_remote_backend(remote_host, session_id, working_dir, on_output,
                                   session_name=session_name, viewer_probe=viewer_probe)

    from src.core.tmux_backend import DEFAULT_SOCKET_NAME, TmuxBackend
    from src.utils.pty_session import PTYBackend

    requested = "auto"
    socket_name = DEFAULT_SOCKET_NAME
    if settings_obj is not None:
        try:
            auth_config = settings_obj.load_auth_config()
            requested = getattr(auth_config.session, "backend", "auto")
            socket_name = getattr(
                auth_config.session, "tmux_socket_name", DEFAULT_SOCKET_NAME
            )
        except (OSError, ValueError, AttributeError) as exc:
            logger.warning(
                "backend_selection_config_load_failed",
                error=str(exc),
                fallback="auto",
            )
    if socket_name_override is not None:
        socket_name = socket_name_override

    if requested == "pty":
        logger.info("session_backend_selected", backend="pty", reason="forced")
        return PTYBackend(session_id, working_dir, on_output)

    probe = probe_tmux()

    if probe.state == TMUX_UNDETERMINED:
        logger.error(
            "session_backend_tmux_undetermined",
            backend="pty",
            reason=requested,
            tmux_path=probe.path,
            detail=probe.detail,
            hint=(
                "tmux was found but could not be run, so the tmux backend was "
                "NOT selected. Sessions will not survive a server restart "
                "until this is resolved."
            ),
        )
        return PTYBackend(session_id, working_dir, on_output)

    if requested == "tmux" and probe.state != TMUX_AVAILABLE:
        logger.warning(
            "session_backend_tmux_requested_but_missing",
            fallback="pty",
            detail=probe.detail,
            hint="install with: brew install tmux",
        )
        return PTYBackend(session_id, working_dir, on_output)

    if probe.usable:
        _selected_log(socket_name, probe.path)(
            "session_backend_selected",
            backend="tmux",
            reason=requested,
            socket_name=socket_name,
            tmux_path=probe.path,
            tmux_version=probe.version,
        )
        return TmuxBackend(
            session_id,
            working_dir,
            on_output,
            socket_name=socket_name,
            session_name=session_name,
            viewer_probe=viewer_probe,
        )

    logger.warning(
        "session_backend_auto_fallback_to_pty",
        reason="tmux_not_installed",
        detail=probe.detail,
        hint="install with: brew install tmux",
    )
    return PTYBackend(session_id, working_dir, on_output)

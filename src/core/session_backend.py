
from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.core.tmux_discovery import (
    TMUX_AVAILABLE,
    TMUX_UNDETERMINED,
    probe_tmux,
)
from src.core.tmux_listing import TmuxListing

logger = structlog.get_logger()


class SessionBackend(ABC):

    replay_in_progress: bool = False

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
        """Paste one body into the pane and submit it with exactly ONE Enter.

        Deliberately NOT a special case of :meth:`write`, which picks its
        delivery route by payload size and would type a short body instead
        of pasting it. An implementation MUST force the paste route
        whatever the length, MUST append no newline to the body, MUST wait
        for measured evidence that the paste actually landed before it
        submits, and MUST NOT submit at all if that evidence never
        arrives - submitting into a pane that never received the body
        sends whatever was already sitting in the prompt.

        The caller is responsible for establishing that the pane is a live
        agent and that the body is safe; see
        :mod:`src.core.session_one_shot_gate`.

        Args:
            text: the body to paste, already sanitised.
            gate: optional async callback that re-checks the caller's gates
                INSIDE the per-pane paste lock, raising to refuse; a backend
                with no lock may run it once before pasting.

        Raises:
            NotImplementedError: backends with no paste channel.
            RuntimeError: the paste could not be confirmed to have landed,
                in which case nothing was submitted.
        """

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
        """Rehydrate state for a session that already exists on the backend.

        Called by SessionManager.lifespan_startup() when it has matched existing
        backend state against persisted metadata. The backend should mark itself
        running, re-open any file handles or pipes needed to stream output, and
        spawn the reader task.

        Unlike ``start()``, this must NOT create a new underlying session - it
        re-wires the Python-side state to an already-alive backend entity.

        Default implementation raises NotImplementedError; backends that
        actually persist across process boundaries (tmux) MUST override.
        """
        raise NotImplementedError("This backend does not support rehydration")

    @abstractmethod
    def discover_existing(self) -> TmuxListing:
        pass

    def list_attachable_sessions(
        self,
        owned_names: Optional[set] = None,
        owned_instances: Optional[set] = None,
    ) -> TmuxListing:
        """Return all sessions on this backend's addressable surface.

        The result is a :class:`~src.core.tmux_listing.TmuxListing`, not a
        bare list: an empty ``sessions`` with ``ok=True`` means genuinely
        no sessions, while ``ok=False`` means the probe could not answer
        and the caller must render "cannot determine", never zero.

        Each dict MUST contain:
            - ``name`` (str): tmux session name as returned by
              ``#{session_name}``.
            - ``created_by_cloude`` (bool): resolved from
              ``owned_instances`` when supplied (a ``(tmux_name, epoch)``
              set sourced from ``sessions.origin``, which identifies the
              tmux INSTANCE rather than the reusable name); otherwise
              True iff ``name`` appears in
              ``owned_names``. Backends that don't cross-reference an
              owned-set fall back to backend-specific heuristics.
            - ``created_at_epoch`` (int): UNIX epoch seconds from
              ``#{session_created}``.
            - ``window_count`` (int): from ``#{session_windows}``.

        Args:
            owned_names: the SessionManager-persisted set of session names
                Cloude Code created. Used to set ``created_by_cloude``
                truthfully rather than leaning on the ``cloude_*`` prefix
                heuristic (which a user could spoof with their own
                ``tmux -L cloude new -s cloude_whatever``).

        Default implementation returns ``[]`` - backends that can't
        enumerate cross-process state (PTY) inherit that behavior. Tmux
        overrides.
        """
        return []

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
        from src.core.hosts.remote_backend import RemoteTmuxBackend

        logger.info("session_backend_selected", backend="remote_tmux", host=remote_host.host_key)
        return RemoteTmuxBackend(remote_host, session_id, working_dir, on_output,
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
        except Exception as exc:
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
        # could not
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

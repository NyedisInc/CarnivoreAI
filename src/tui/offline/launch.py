
from __future__ import annotations

import os
import sys
from typing import Any, TextIO

import httpx
import structlog

from src.core.tmux_discovery import resolve_tmux_path
from src.core.tmux_socket_resolution import configured_tmux_socket_name
from src.tui.offline.names import offline_state_dir
from src.tui.offline.socket_check import SocketRefused, TmuxMissing, resolve_offline
from src.tui.offline.tmux_cmd import OfflineTmuxError, TmuxNotRunning
from src.tui.strings import t

logger = structlog.get_logger(__name__)

VERSION_PATH = "/api/v1/version"
PROBE_TIMEOUT_SECONDS = 0.5
EXIT_REFUSED = 2
EXIT_FAILED = 1
EXIT_NOT_RUNNING = 3


def server_answers(base_url: str, timeout: float = PROBE_TIMEOUT_SECONDS) -> bool:
    try:
        httpx.get(base_url + VERSION_PATH, timeout=timeout, trust_env=False)
    except (httpx.ConnectError, httpx.TimeoutException):
        return False
    except httpx.HTTPError as err:
        logger.info("tui_server_probe_odd_answer", error=type(err).__name__)
    return True


def offline_message(err: OfflineTmuxError) -> tuple[str, int]:
    if isinstance(err, SocketRefused):
        text = t("tui.offline.refused").replace("{reason}", t(f"tui.offline.reason.{err.reason}"))
        return text.replace("{path}", err.path), EXIT_REFUSED
    if isinstance(err, TmuxNotRunning):
        return t("tui.offline.not_running"), EXIT_NOT_RUNNING
    if isinstance(err, TmuxMissing):
        return t("tui.offline.no_tmux"), EXIT_FAILED
    return t("tui.offline.failed").replace("{detail}", str(err)), EXIT_FAILED


def run_offline(settings_obj: Any, out: TextIO = sys.stderr) -> int:
    try:
        context = resolve_offline(
            configured_tmux_socket_name(settings_obj), os.environ, os.getuid(), resolve_tmux_path()
        )
    except OfflineTmuxError as err:
        text, code = offline_message(err)
        print(text, file=out)
        return code
    from src.tui.offline.app import OfflineTui

    OfflineTui(context, offline_state_dir(settings_obj.state_dir_override)).run()
    return 0

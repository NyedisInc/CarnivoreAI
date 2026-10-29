
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence

import structlog

from src.core.tmux_command_batch import TmuxCommand

logger = structlog.get_logger()

SERVER_CONFIG_FILENAME: str = "cloude-tmux.conf"

_UNSAFE_IN_LINE: str = " \t\n\r\"'\\#;$"


def render_config_line(command: TmuxCommand) -> Optional[str]:
    tokens = [str(token) for token in command]
    if not tokens:
        return None
    for token in tokens:
        if not token or any(char in token for char in _UNSAFE_IN_LINE):
            return None
    return " ".join(tokens)


def render_config(commands: Sequence[TmuxCommand]) -> Optional[str]:
    if not commands:
        return None
    lines: List[str] = []
    for command in commands:
        line = render_config_line(command)
        if line is None:
            logger.warning(
                "tmux_server_config_refused",
                reason="a token cannot be expressed as a config line",
                command=" ".join(str(token) for token in command),
            )
            return None
        lines.append(line)
    return "".join(f"{line}\n" for line in lines)


def write_server_config(
    directory: Path, commands: Sequence[TmuxCommand]
) -> Optional[Path]:
    body = render_config(commands)
    if body is None:
        return None

    target = directory / SERVER_CONFIG_FILENAME
    tmp_name: Optional[str] = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(
            prefix=f".{SERVER_CONFIG_FILENAME}.", suffix=".tmp", dir=str(directory)
        )
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, target)
        tmp_name = None
        return target
    except (OSError, ValueError) as exc:
        logger.warning(
            "tmux_server_config_write_failed",
            path=str(target),
            error=f"{type(exc).__name__}: {exc}",
        )
        return None
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

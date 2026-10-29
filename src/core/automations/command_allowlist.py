
from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core import resource_push
from src.core.resource_push import topics

logger = structlog.get_logger()

CONFIG_KEY = "automation_commands"
ENTRY_MAX = 500
LIST_MAX = 50


class CommandListInvalid(ValueError):

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def config_path() -> Path:
    from src.config import settings  # noqa: PLC0415

    return Path(settings.auth_config_file).expanduser()


def argv_of(entry: str) -> List[str]:
    return shlex.split(entry)


def clean_entry(value: Any) -> str:
    if not isinstance(value, str):
        raise CommandListInvalid("command_invalid", "text")
    text = value.strip()
    if not text or len(text) > ENTRY_MAX or any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise CommandListInvalid("command_invalid", f"one line of 1 to {ENTRY_MAX} characters")
    try:
        argv = argv_of(text)
    except ValueError as exc:
        raise CommandListInvalid("command_invalid", "unbalanced quotes") from exc
    if not argv or not os.path.isabs(argv[0]):
        raise CommandListInvalid("command_invalid", "start with the program's absolute path")
    return text


def clean_list(values: Any) -> List[str]:
    if not isinstance(values, (list, tuple)):
        raise CommandListInvalid("command_invalid", "a list of commands")
    out: List[str] = []
    for value in values:
        entry = clean_entry(value)
        if entry not in out:
            out.append(entry)
    if len(out) > LIST_MAX:
        raise CommandListInvalid("commands_too_many", f"at most {LIST_MAX}")
    return out


def read(path: Optional[Path] = None) -> List[str]:
    from src.core import config_writer  # noqa: PLC0415

    try:
        config: Dict[str, Any] = config_writer.read_config(path or config_path())
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("automation_commands_config_unreadable", error_type=type(exc).__name__)
        return []
    raw = config.get(CONFIG_KEY) if isinstance(config, dict) else None
    if not isinstance(raw, list):
        return []
    try:
        return clean_list(raw)
    except CommandListInvalid as exc:
        logger.warning("automation_commands_block_invalid", code=exc.code)
        return []


def allows(command: Any, path: Optional[Path] = None) -> bool:
    return isinstance(command, str) and command in read(path)


def save(entries: Any, path: Optional[Path] = None) -> List[str]:
    from src.core import config_writer  # noqa: PLC0415

    clean = clean_list(entries)

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None if config.get(CONFIG_KEY) == clean else {**config, CONFIG_KEY: clean}

    outcome = config_writer.commit(path or config_path(), mutate)
    if outcome.wrote:
        resource_push.notify(topics.AUTOMATION_COMMANDS)
    logger.info("automation_commands_saved", count=len(clean), changed=outcome.wrote)
    return clean


from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from src.core import config_writer
from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.session_transcript_presence import CONVERSATION_PRESENT, family_conversation_presence
from src.core.test_write_guard import assert_test_write_allowed
from src.core.time_machine import limits
from src.core.time_machine.constants import CAP_ENV_VAR, DEFAULT_CAP_BYTES, LIMITS_FILE_NAME, TREE_DIR_NAME
from src.core.transcript_source import dataless, scope as source_scope
from src.core.transcript_source.constants import FAMILY_CODEX
from src.core.transcript_source.entries import claude_user_text, codex_user_text
from src.core.transcript_source.locate import SourceSet, locate
from src.core.transcript_source.scope import SCOPE_ALL, SCOPE_HUMAN, SCOPE_SUBSESSIONS


def state_dir() -> Path:
    from src.config import settings  # noqa: PLC0415

    return Path(settings.get_state_dir())


def projects_dir() -> Path:
    from src.core.claude_transcript_correlate import default_projects_dir  # noqa: PLC0415

    return Path(default_projects_dir())


def default_codex_home() -> Path:
    from src.core.attention import codex_gather  # noqa: PLC0415

    return Path(codex_gather.DEFAULT_CODEX_HOME)


def config_file() -> Path:
    from src.config import settings  # noqa: PLC0415

    return Path(settings.auth_config_file).expanduser()


def read_config(path: Path) -> Dict[str, Any]:
    return config_writer.read_config(path)


def commit_config(path: Path, mutate: Callable[[Dict[str, Any]], None]) -> None:
    config_writer.commit(path, mutate)


def announce_timeline() -> None:
    from src.core.session_timeline import push  # noqa: PLC0415

    push.announce()


__all__ = [
    "CAP_ENV_VAR", "CONVERSATION_PRESENT", "DEFAULT_CAP_BYTES", "FAMILY_CODEX", "LIMITS_FILE_NAME", "SCOPE_ALL",
    "SCOPE_HUMAN", "SCOPE_SUBSESSIONS", "SourceSet", "TREE_DIR_NAME", "announce_timeline", "assert_test_write_allowed",
    "claude_user_text", "codex_user_text", "commit_config", "config_file", "dataless", "default_codex_home", "family_conversation_presence",
    "limits", "locate", "projects_dir", "read_config", "slugify_project_dir", "source_scope", "state_dir",
]

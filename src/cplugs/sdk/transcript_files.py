"""What the save plugin's restore point engine needs from the app: transcript files, where they live, and the tree's config.

Issue #1675. The engine (``src/cplugs/save/engine/``) copies a conversation's transcript files into
``<state>/time-machine/`` and puts them back on a restore. A plugin imports only the SDK
(``tests/python/cplugs/test_cplug_boundaries.py``), so every core piece the engine reads arrives here, by name:

- where things are: :func:`state_dir` (this install's state directory, the tree's parent) and :func:`projects_dir`
  (Claude Code's ``~/.claude/projects``); tests replace both;
- finding a conversation's files: :func:`locate` and :class:`SourceSet` (``transcript_source.locate``), the iCloud
  placeholder checks (``dataless``), the capture scope rules (``source_scope``, ``SCOPE_*``), the first prompt
  readers (:func:`claude_user_text`, :func:`codex_user_text`), the folder name a working dir maps to
  (:func:`slugify_project_dir`) and whether a conversation is already on disk (:func:`family_conversation_presence`);
- writing: :func:`assert_test_write_allowed` (the test write guard), the one config writer
  (:func:`read_config`, :func:`commit_config`, :func:`config_file`) for the capture scope in ``config.json``, and
  :func:`announce_timeline` (a point was written or removed: the session timeline repaints);
- the storage cap: ``limits`` (``limits.json``, which core shares with the summary settings) and the four names core
  owns (``TREE_DIR_NAME``, ``DEFAULT_CAP_BYTES``, ``CAP_ENV_VAR``, ``LIMITS_FILE_NAME``).

Every name is the core object itself, not a copy, so there is one source of truth for each.
"""

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
    """This install's state directory (the restore point tree is ``<it>/time-machine``). Output: Path."""
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

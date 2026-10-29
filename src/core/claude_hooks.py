
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import structlog

from src.core.config_files_io import atomic_write
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()


CLOUDECODE_HOOKS_MARKER = "# cloudecode-managed"

TOAST_EVENTS = ("Stop", "Notification", "PermissionRequest")

ACTIVITY_ONLY_EVENTS = (
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SubagentStart",
    "SubagentStop",
)

LIFECYCLE_EVENTS = ("SessionStart", "SessionEnd")

WORK_EVENTS = TOAST_EVENTS + ACTIVITY_ONLY_EVENTS


def _is_managed_command(cmd: Any) -> bool:
    return isinstance(cmd, str) and CLOUDECODE_HOOKS_MARKER in cmd


def _filter_user_matchers(
    matchers: list[Any], event: str
) -> list[Any]:
    keep: list[Any] = []
    for matcher_entry in matchers:
        if not isinstance(matcher_entry, dict):
            keep.append(matcher_entry)
            continue
        inner_hooks = matcher_entry.get("hooks", [])
        if not isinstance(inner_hooks, list):
            keep.append(matcher_entry)
            continue
        if any(
            isinstance(h, dict) and _is_managed_command(h.get("command"))
            for h in inner_hooks
        ):
            continue
        keep.append(matcher_entry)
    return keep


SETTINGS_PATH_ENV_VAR = "CLOUDE_CLAUDE_SETTINGS_PATH"


def default_settings_path() -> Path:
    override = os.environ.get(SETTINGS_PATH_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "settings.json"


def strip_managed_hooks(settings_path: Path) -> bool:
    path = settings_path

    assert_test_write_allowed(path)

    if not path.exists():
        return True

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "claude_settings_read_failed", path=str(path), error=str(exc)
        )
        return False

    if not raw.strip():
        return True

    try:
        existing = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "claude_settings_unparseable", path=str(path), error=str(exc)
        )
        return False

    if not isinstance(existing, dict):
        logger.warning(
            "claude_settings_not_object",
            path=str(path),
            type=type(existing).__name__,
        )
        return False

    hooks_block = existing.get("hooks")
    if not isinstance(hooks_block, dict):
        return True

    stripped: dict[str, Any] = {}
    removed: list[str] = []
    for event, matchers in hooks_block.items():
        if not isinstance(matchers, list):
            stripped[event] = matchers
            continue
        kept = _filter_user_matchers(matchers, event)
        if len(kept) != len(matchers):
            removed.append(event)
        if not kept and matchers:
            continue
        stripped[event] = kept

    if not removed:
        return True

    merged = dict(existing)
    if stripped:
        merged["hooks"] = stripped
    else:
        merged.pop("hooks", None)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        target = path.resolve()
        atomic_write(
            target,
            json.dumps(merged, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
            mode=stat.S_IMODE(target.stat().st_mode),
        )
        logger.info(
            "claude_hooks_settings_stripped",
            path=str(path),
            events=removed,
        )
        return True
    except OSError as exc:
        logger.warning(
            "claude_hooks_settings_strip_failed",
            path=str(path),
            error=str(exc),
        )
        return False

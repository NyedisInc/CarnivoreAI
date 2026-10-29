"""Removing cloudecode's managed hook block from ``~/.claude/settings.json``.

THIS MODULE USED TO INSTALL HOOKS. IT NOW ONLY TAKES THEM BACK OUT.

CloudeCode learned a session's state by making Claude Code POST every
lifecycle event to a loopback endpoint. That was measured wrong nine
times in ten, because ``CLOUDECODE_SESSION_ID`` is a PANE-WIDE
environment variable: the parent agent and every background agent it
spawned posted under one session id, so a sub-agent's own tool call
looked exactly like the user's turn resuming. The whole subsystem is
gone, replaced by passive detection that reads what the harness already
writes to disk (``src/core/attention/``).

So the one job left here is CLEANING UP AFTER THE OLD VERSION. An install
that ran any earlier build has our block sitting in the user's settings
file, pointing at an endpoint that no longer exists, making Claude Code
pay for a curl on every single event forever. :func:`strip_managed_hooks`
is called once at startup and removes it.

What it must never do:

- **Touch a hook the user wrote.** Every managed command carries the
  literal marker ``# cloudecode-managed``. Only entries bearing it are
  dropped; everything else is written back byte-for-byte.
- **Clobber a file it could not parse.** A read error or a syntax error
  LOGS and BAILS, exactly as the old merge did.
- **Leave litter behind.** An event key whose matcher list is emptied by
  the strip is removed, and a ``hooks`` key emptied by that is removed
  too, so a user who never had hooks of their own is left with the file
  they would have had if CloudeCode had never run.
- **Skip anyone.** There is deliberately NO opt-out check. The old
  ``disable_claude_hooks`` setting is gone, and honouring it here would
  skip the cleanup for exactly the users who asked not to have the block
  in the first place - the ones most likely to still be carrying one
  from before they set the flag.

The write is atomic: write-to-tmp + rename. The file is left untouched
when there was nothing of ours in it, so a steady-state boot does not
rewrite the user's settings at all.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import structlog

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

# waiting on the user
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
        tmp = path.with_suffix(path.suffix + ".cloudecode-tmp")
        tmp.write_text(
            json.dumps(merged, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
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

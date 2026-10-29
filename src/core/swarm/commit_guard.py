
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import structlog

from src.core.swarm import memory

logger = structlog.get_logger(__name__)

HOOK_NAMES = (
    "applypatch-msg", "pre-applypatch", "post-applypatch", "pre-commit", "pre-merge-commit", "prepare-commit-msg",
    "commit-msg", "post-commit", "pre-rebase", "post-checkout", "post-merge", "pre-push", "pre-receive", "update",
    "post-receive", "post-update", "reference-transaction", "pre-auto-gc", "post-rewrite", "sendemail-validate",
    "post-index-change",
)

ENV_KEYS = ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0")

DISPATCHER = """#!/bin/sh
# Carnivore Swarm commit guard (issue #1458). Written by src/core/swarm/commit_guard.py at every agent launch.
# Refuses this agent's codename in a commit message, then runs the repo's own hook of the same name.
here=$(cd "$(dirname "$0")" && pwd -P)
name=$(basename "$0")
if [ "$name" = commit-msg ] && [ -s "$here/codename" ]; then
  if grep -v '^#' "$1" | grep -qiwF -f "$here/codename"; then
    echo "commit refused: the message names this agent's codename ($(cat "$here/codename")). Use the plain job instead." >&2
    exit 1
  fi
fi
own=$(env -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u GIT_CONFIG_VALUE_0 git config --path core.hooksPath 2>/dev/null)
[ -n "$own" ] || own="$(git rev-parse --git-common-dir 2>/dev/null)/hooks"
if [ -x "$own/$name" ] && [ "$(cd "$own" 2>/dev/null && pwd -P)" != "$here" ]; then
  exec "$own/$name" "$@"
fi
exit 0
"""


def codename(agent: Dict[str, Any]) -> str:
    return " ".join(str(agent.get("persona") or "").split())


def hooks_dir(state_dir: Path, agent_id: int) -> Path:
    return Path(state_dir) / "swarm" / "hooks" / str(int(agent_id))


def guard_env(hooks: Path) -> Dict[str, str]:
    return dict(zip(ENV_KEYS, ("1", "core.hooksPath", str(hooks))))


def _write_if_changed(path: Path, text: str, mode: int) -> None:
    try:
        same = path.read_text(encoding="utf-8") == text
    except (FileNotFoundError, UnicodeDecodeError):
        same = False
    if not same:
        memory.atomic_write(path, text)
    if (path.stat().st_mode & 0o777) != mode:
        os.chmod(path, mode)


def write_hooks(state_dir: Path, agent: Dict[str, Any], name: str) -> Path:
    hooks = hooks_dir(state_dir, agent["id"])
    _write_if_changed(hooks / "codename", name + "\n", 0o644)
    for hook in HOOK_NAMES:
        _write_if_changed(hooks / hook, DISPATCHER, 0o755)
    return hooks


def apply(state_dir: Path, agent: Dict[str, Any], settings_file: Path) -> bool:
    name = codename(agent)
    try:
        data = json.loads(settings_file.read_text(encoding="utf-8")) if settings_file.exists() else {}
        if not isinstance(data, dict):
            raise ValueError("settings file is not a JSON object")
        env = dict(data.get("env") or {})
        if name:
            env.update(guard_env(write_hooks(state_dir, agent, name)))
        else:
            for key in ENV_KEYS:
                env.pop(key, None)
        updated = {**data, "env": env} if env else {k: v for k, v in data.items() if k != "env"}
        if updated != data:
            memory.atomic_write(settings_file, json.dumps(updated, indent=2) + "\n")
    except (OSError, ValueError) as exc:
        logger.warning("swarm_commit_guard_unwritten", agent_id=agent.get("id"), error=type(exc).__name__)
        return False
    return bool(name)

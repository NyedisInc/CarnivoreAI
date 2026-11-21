
from __future__ import annotations

import json
import os
import re
import stat
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from src.core.claude_hooks import _is_managed_command
from src.core.config_files_io import atomic_write, atomic_write_bytes
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

CODEX_DIR_ENV_VAR = "CLOUDE_CODEX_DIR"

_TRUST_HEADER = re.compile(r'^\[hooks\.state\."(?P<path>.+):(?P<event>[a-z_]+):(?P<matcher>\d+):(?P<hook>\d+)"\]\s*$')


def default_codex_dir() -> Path:
    override = os.environ.get(CODEX_DIR_ENV_VAR) or os.environ.get("CODEX_HOME")
    return Path(override).expanduser() if override else Path.home() / ".codex"


def _snake(event: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()


def _is_managed_matcher(entry: Any) -> bool:
    if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
        return False
    return any(isinstance(h, dict) and _is_managed_command(h.get("command")) for h in entry["hooks"])


def _backup(path: Path, raw: bytes) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    atomic_write_bytes(path.with_name(f"{path.name}.cloudecode-bak-{stamp}"), raw, stat.S_IMODE(path.stat().st_mode))


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("codex_hooks_read_failed", path=str(path), error=str(exc))
        return None


def _rewrite_trust(toml_text: str, prefixes: set[str], dropped: set[tuple[str, int]],
                   renumber: dict[tuple[str, int], int]) -> tuple[str, int, int]:
    lines = toml_text.splitlines(keepends=True)
    out: list[str] = []
    removed = moved = 0
    skipping = False
    for line in lines:
        if line.startswith("["):
            skipping = False
            m = _TRUST_HEADER.match(line.rstrip("\r\n"))
            if m and m["path"] in prefixes:
                key = (m["event"], int(m["matcher"]))
                if key in dropped:
                    skipping = True
                    removed += 1
                    continue
                if key in renumber:
                    line = line.replace(
                        f':{m["event"]}:{m["matcher"]}:{m["hook"]}"]', f':{m["event"]}:{renumber[key]}:{m["hook"]}"]', 1)
                    moved += 1
        if not skipping:
            out.append(line)
    return "".join(out), removed, moved


def strip_codex_managed_hooks(codex_dir: Path) -> bool:
    hooks_path = codex_dir / "hooks.json"
    toml_path = codex_dir / "config.toml"
    assert_test_write_allowed(hooks_path)
    raw = _read(hooks_path)
    if raw is None or not raw.strip():
        return True
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("codex_hooks_unparseable", path=str(hooks_path), error=str(exc))
        return False
    block = doc.get("hooks") if isinstance(doc, dict) else None
    if not isinstance(block, dict):
        return True

    dropped: set[tuple[str, int]] = set()
    renumber: dict[tuple[str, int], int] = {}
    kept_block: dict[str, Any] = {}
    for event, matchers in block.items():
        if not isinstance(matchers, list):
            kept_block[event] = matchers
            continue
        kept: list[Any] = []
        for old, entry in enumerate(matchers):
            if _is_managed_matcher(entry):
                dropped.add((_snake(event), old))
                continue
            if len(kept) != old:
                renumber[(_snake(event), old)] = len(kept)
            kept.append(entry)
        if kept or not matchers:
            kept_block[event] = kept
    if not dropped:
        return True

    new_doc = dict(doc)
    if kept_block:
        new_doc["hooks"] = kept_block
    else:
        new_doc.pop("hooks", None)

    toml_plan: tuple[bytes, str] | None = None
    toml_raw = _read(toml_path)
    if toml_raw is not None:
        try:
            tomllib.loads(toml_raw.decode("utf-8"))
            prefixes = {str(hooks_path), str(hooks_path.resolve())}
            new_toml, removed, moved = _rewrite_trust(toml_raw.decode("utf-8"), prefixes, dropped, renumber)
            tomllib.loads(new_toml)
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            logger.warning("codex_config_unparseable", path=str(toml_path), error=str(exc))
            return False
        if removed or moved:
            toml_plan = (toml_raw, new_toml)

    try:
        target = hooks_path.resolve()
        _backup(target, raw)
        atomic_write(target, json.dumps(new_doc, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
                     mode=stat.S_IMODE(target.stat().st_mode))
        if toml_plan is not None:
            toml_target = toml_path.resolve()
            _backup(toml_target, toml_plan[0])
            atomic_write(toml_target, toml_plan[1], mode=stat.S_IMODE(toml_target.stat().st_mode))
        logger.info("codex_hooks_stripped", path=str(hooks_path), entries=len(dropped), trust_tables=bool(toml_plan))
        return True
    except OSError as exc:
        logger.warning("codex_hooks_strip_failed", path=str(hooks_path), error=str(exc))
        return False

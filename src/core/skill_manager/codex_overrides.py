
from __future__ import annotations

import os
import threading
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.config_files_io import atomic_write
from src.core.skill_manager import codex_toml
from src.core.skill_manager.types import OverrideError
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

MAX_CONFIG_BYTES = 2 * 1024 * 1024


def read_codex_rules(config_path: str) -> Optional[List[Tuple[str, str, bool]]]:
    real = os.path.realpath(os.path.expanduser(config_path))
    try:
        if os.path.getsize(real) > MAX_CONFIG_BYTES:
            return None
        with open(real, "rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return []
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("skill_manager_codex_config_unparseable", path=real, error=type(exc).__name__)
        return None
    return rules_from_data(data)


def rules_from_data(data: Dict[str, Any]) -> List[Tuple[str, str, bool]]:
    block = data.get("skills")
    rules = block.get("config") if isinstance(block, dict) else None
    out: List[Tuple[str, str, bool]] = []
    for rule in rules if isinstance(rules, list) else []:
        if not isinstance(rule, dict) or not isinstance(rule.get("enabled"), bool):
            continue
        has_path, has_name = isinstance(rule.get("path"), str), isinstance(rule.get("name"), str)
        if has_path == has_name:
            continue
        kind = "path" if has_path else "name"
        out.append((kind, str(rule[kind]), rule["enabled"]))
    return out


def codex_enabled(rules: List[Tuple[str, str, bool]], name: str, skill_md: str) -> Tuple[bool, bool]:
    enabled, matched = True, False
    for kind, value, on in rules:
        if (kind == "name" and value == name) or (kind == "path" and os.path.realpath(value) == skill_md):
            enabled, matched = on, True
    return enabled, matched


_write_lock = threading.Lock()


def _identity(path: Path) -> Optional[Tuple[int, int, int]]:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def write_codex_rule(codex_home: Path, kind: str, value: str, enabled: bool) -> bool:
    if not codex_home.is_dir():
        raise OverrideError(404, "codex_not_installed", "there is no Codex home folder on this machine")
    real = Path(os.path.realpath(codex_home / "config.toml"))
    assert_test_write_allowed(real)
    with _write_lock:
        seen = _identity(real)
        try:
            if seen is not None and seen[2] > MAX_CONFIG_BYTES:
                raise ValueError("too large")
            before = real.read_text(encoding="utf-8") if seen is not None else ""
            tomllib.loads(before)
        except (OSError, ValueError) as exc:
            logger.warning("skill_manager_codex_config_unparseable", path=str(real), error=type(exc).__name__)
            raise OverrideError(409, "settings_unparseable", "config.toml could not be read as TOML") from exc
        after = codex_toml.set_skill_rule(before, kind, value, enabled)
        if after == before:
            return False
        codex_toml.check_edit_safe(before, after)
        expected, _ = codex_enabled(
            rules_from_data(tomllib.loads(after)),
            value if kind == "name" else "",
            os.path.realpath(value) if kind == "path" else "",
        )
        if expected != enabled:
            raise OverrideError(409, "codex_config_edit_unsafe", "the edited rule does not say what was asked")
        mode = (real.stat().st_mode & 0o777) if seen is not None else 0o600
        if seen is not None:
            atomic_write(real.with_name(real.name + ".bak"), before, mode)
        if _identity(real) != seen:
            raise OverrideError(409, "settings_changed", "config.toml changed while it was being edited")
        atomic_write(real, after, mode)
    logger.info("skill_manager_override_written", harness="codex", rule=kind, cleared=enabled)
    return True

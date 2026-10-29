
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import structlog

from src.core import config_writer
from src.core.resource_push import notifier
from src.core.resource_push.topics import MODS
from src.core.skill_manager.claude_overrides import MAX_SETTINGS_BYTES
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

ENV_KEY = "CLAUDE_CODE_PLUGIN_DIRS"

OK, MISSING, UNPARSEABLE, CHANGED, UNWRITABLE = (
    "ok", "settings_missing", "settings_unparseable", "settings_changed", "settings_unwritable")

NEW_FILE_MODE = 0o600


@dataclass(frozen=True)
class Group:

    real: Path
    members: tuple
    creatable: bool

    @property
    def label(self) -> str:
        return self.members[0].parent.name + (f" +{len(self.members) - 1} linked" if len(self.members) > 1 else "")


def groups_for(home: Path, account_files: Sequence[Path]) -> List[Group]:
    primary = home / ".claude" / "settings.json"
    order: Dict[str, List[Path]] = {}
    for path in [primary, *account_files]:
        order.setdefault(os.path.realpath(path), []).append(Path(path))
    primary_real = os.path.realpath(primary)
    return [Group(Path(real), tuple(members), real == primary_real) for real, members in order.items()]


def split_entries(value: Any) -> List[str]:
    if not isinstance(value, str):
        raise ValueError(f"{ENV_KEY} is not a string")
    return [part for part in value.split(":") if part]


def _same(entry: str, path: str) -> bool:
    return os.path.realpath(os.path.expanduser(entry)) == os.path.realpath(path)


def _mutator(path: str, enabled: bool):

    def mutate(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(doc, dict):
            raise ValueError("settings file is not a JSON object")
        env = doc.get("env")
        if env is not None and not isinstance(env, dict):
            raise ValueError("env is not a JSON object")
        env = dict(env or {})
        entries = split_entries(env[ENV_KEY]) if ENV_KEY in env else []
        if enabled:
            if any(_same(e, path) for e in entries):
                return None
            entries.append(path)
        else:
            kept = [e for e in entries if not _same(e, path)]
            if len(kept) == len(entries):
                return None
            entries = kept
        if entries:
            env[ENV_KEY] = ":".join(entries)
        else:
            env.pop(ENV_KEY, None)
        return {**{k: v for k, v in doc.items() if k != "env"}, "env": env}

    return mutate


def _write_group(group: Group, path: str, enabled: bool) -> str:
    """Apply one change to one real file, never raising on a filesystem error.

    Output: one of OK, MISSING, UNPARSEABLE, CHANGED, UNWRITABLE (a backup or write failed; nothing was written).
    """
    try:
        return _write_group_inner(group, path, enabled)
    except OSError as exc:
        logger.warning("mods_settings_unwritable", path=str(group.real), error=type(exc).__name__)
        return UNWRITABLE


def _write_group_inner(group: Group, path: str, enabled: bool) -> str:
    real = group.real
    assert_test_write_allowed(real)
    try:
        mode = real.stat().st_mode & 0o777
        size = real.stat().st_size
    except FileNotFoundError:
        if not group.creatable:
            return MISSING
        if not enabled:
            return OK
        if not real.parent.is_dir():
            return MISSING
        config_writer.create_if_absent(real, {}, file_mode=NEW_FILE_MODE)
        mode, size = NEW_FILE_MODE, 0
    if size > MAX_SETTINGS_BYTES:
        return UNPARSEABLE
    for _ in (1, 2):
        try:
            outcome = config_writer.commit(real, _mutator(path, enabled), file_mode=mode,
                                           external_writer=True, backup=True, backup_required=True)
        except ValueError as exc:
            logger.warning("mods_settings_unparseable", path=str(real), error=type(exc).__name__)
            return UNPARSEABLE
        except FileNotFoundError:
            return CHANGED
        if outcome.status in (config_writer.COMMITTED, config_writer.UNCHANGED):
            return OK
        if outcome.status != config_writer.STALE_REVISION:
            logger.warning("mods_settings_not_written", path=str(real), status=outcome.status)
            return UNWRITABLE
    return CHANGED


def read_group(group: Group) -> Dict[str, Any]:
    import json

    try:
        if group.real.stat().st_size > MAX_SETTINGS_BYTES:
            return {"status": UNPARSEABLE, "entries": []}
        doc = json.loads(group.real.read_text(encoding="utf-8"))
        env = doc.get("env") if isinstance(doc, dict) else None
        if not isinstance(doc, dict) or (env is not None and not isinstance(env, dict)):
            raise ValueError("unexpected settings shape")
        return {"status": OK, "entries": split_entries((env or {}).get(ENV_KEY, ""))}
    except FileNotFoundError:
        return {"status": MISSING, "entries": []}
    except (ValueError, OSError):
        return {"status": UNPARSEABLE, "entries": []}


def set_registered(path: str, enabled: bool, *, home: Path, account_files: Sequence[Path]) -> List[Dict[str, Any]]:
    if not os.path.isabs(path):
        raise ValueError("the mod path must be absolute")
    results = []
    for group in groups_for(home, account_files):
        before = read_group(group)
        status = _write_group(group, path, enabled)
        results.append({"real": str(group.real), "members": [str(m) for m in group.members], "status": status,
                        "_changed": status == OK and before != read_group(group)})
    if any(r["_changed"] for r in results):
        notifier.notify(MODS)
    for r in results:
        del r["_changed"]
    return results


def register(path: str, *, home: Path, account_files: Sequence[Path]) -> List[Dict[str, Any]]:
    return set_registered(path, True, home=home, account_files=account_files)


def unregister(path: str, *, home: Path, account_files: Sequence[Path]) -> List[Dict[str, Any]]:
    return set_registered(path, False, home=home, account_files=account_files)

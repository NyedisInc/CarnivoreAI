
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import structlog

from src.core import config_writer

logger = structlog.get_logger()

STATE_FILE = "mods_state.json"


def state_path(state_dir: Optional[Path] = None) -> Path:
    if state_dir is None:
        from src.config import settings

        state_dir = settings.get_state_dir()
    return Path(state_dir) / STATE_FILE


def load(state_dir: Optional[Path] = None) -> Dict[str, Any]:
    try:
        doc = config_writer.read_config(state_path(state_dir))
    except (OSError, ValueError):
        doc = {}
    wanted, restored, offered = doc.get("wanted"), doc.get("restored"), doc.get("offered")
    return {"wanted": wanted if isinstance(wanted, dict) else {},
            "restored": restored if isinstance(restored, dict) else {},
            "offered": offered if isinstance(offered, list) else []}


def _commit(change, state_dir: Optional[Path]) -> None:
    def mutate(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        doc = {"wanted": dict(raw.get("wanted") or {}), "restored": dict(raw.get("restored") or {}),
               "offered": list(raw.get("offered") or [])}
        before = {k: (dict(v) if isinstance(v, dict) else list(v)) for k, v in doc.items()}
        change(doc)
        return None if doc == before else doc

    try:
        path = state_path(state_dir)
        if not path.exists():
            config_writer.create_if_absent(path, {})
        config_writer.commit(path, mutate)
    except (OSError, ValueError) as exc:
        logger.warning("mods_owner_state_unwritable", error=type(exc).__name__)


def record(path: str, enabled: bool, *, state_dir: Optional[Path] = None) -> None:
    key = os.path.realpath(path)

    def change(doc: Dict[str, Any]) -> None:
        doc["wanted"][key] = bool(enabled)
        doc["restored"].pop(key, None)

    _commit(change, state_dir)


def mark_offered(item_id: str, *, state_dir: Optional[Path] = None) -> None:
    _commit(lambda doc: doc["offered"].append(item_id) if item_id not in doc["offered"] else None, state_dir)


def was_offered(item_id: str, *, state_dir: Optional[Path] = None) -> bool:
    return item_id in load(state_dir)["offered"]


def restore_dropped(inventory_mods: Sequence[Dict[str, Any]], *, home: Path, account_files: Sequence[Path],
                    state_dir: Optional[Path] = None) -> List[str]:
    from src.core.mods import registry

    stored = load(state_dir)
    restored: List[str] = []
    for mod in inventory_mods:
        key = os.path.realpath(mod["path"])
        want = stored["wanted"].get(key)
        if want is None:
            if mod["state"] == "on":
                record(mod["path"], True, state_dir=state_dir)
        elif want is True and mod["state"] == "off" and mod["present"] and mod["is_mod"]:
            results = registry.set_registered(mod["path"], True, home=home, account_files=account_files)
            if any(r["status"] == registry.OK for r in results):
                _commit(lambda doc, k=key: doc["restored"].__setitem__(k, datetime.now(timezone.utc).isoformat()), state_dir)
                logger.warning("mod_dropped_restored", name=mod.get("name"))
                restored.append(mod["path"])
    return restored

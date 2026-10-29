
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.core.live_install_roots import CLAUDE_DIR_NAME, MODS_DIR_NAME
from src.core.mods import registry

MIN_CLAUDE_VERSION: Tuple[int, int, int] = (2, 1, 287)


def mod_id_for(path: str) -> str:
    return hashlib.sha256(os.path.realpath(path).encode("utf-8")).hexdigest()[:16]


def mods_root(home: Path) -> Path:
    return home / CLAUDE_DIR_NAME / MODS_DIR_NAME


def is_directly_under(path: str, root: Path) -> bool:
    if ".." in Path(path).parts:
        return False
    parent = os.path.dirname(os.path.normpath(path))
    return os.path.realpath(parent) == os.path.realpath(root)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def declares_modules(folder: str) -> bool:
    hooks = _read_json(Path(folder) / "hooks" / "hooks.json")
    return bool(hooks) and "modules" in hooks


def _describe(folder: str) -> Dict[str, Optional[str]]:
    meta = _read_json(Path(folder) / ".claude-plugin" / "plugin.json") or {}
    pick = lambda key: meta.get(key) if isinstance(meta.get(key), str) else None  # noqa: E731
    return {"name": pick("name") or (os.path.basename(folder.rstrip("/")) or None),
            "version": pick("version"), "description": pick("description")}


def build_inventory(home: Path, account_files: Sequence[Path], ledger_rows: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    groups = registry.groups_for(home, account_files)
    read = [registry.read_group(g) for g in groups]
    found: Dict[str, Dict[str, Any]] = {}

    def add(path: str, **extra: Any) -> None:
        found.setdefault(os.path.realpath(path), {"path": path}).update(extra)

    for row in ledger_rows:
        add(row["path"], source="catalog", install_id=row["install_id"], item_id=row["item_id"])
    for state in read:
        for entry in state["entries"]:
            add(os.path.expanduser(entry))
    root = mods_root(home)
    try:
        children = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        children = []
    for child in children:
        if declares_modules(str(child)):
            add(str(child))

    ledger_real = {os.path.realpath(r["path"]) for r in ledger_rows}
    mods: List[Dict[str, Any]] = []
    for real, info in found.items():
        path = info["path"]
        registered = sum(1 for s in read if s["status"] == registry.OK
                         and any(registry._same(e, path) for e in s["entries"]))
        mods.append({
            "mod_id": mod_id_for(path), **_describe(path), "path": path,
            "source": info.get("source", "local"), "install_id": info.get("install_id"), "item_id": info.get("item_id"),
            "state": "on" if registered == len(groups) else "off" if registered == 0 else "partial",
            "registered_in": registered, "groups_total": len(groups),
            "is_mod": declares_modules(path), "present": os.path.isdir(path),
            "removable": real not in ledger_real and is_directly_under(path, root),
        })
    mods.sort(key=lambda m: (m["name"] or "", m["path"]))
    return {"mods": mods, "groups": [
        {"label": g.label,
         "members": [str(m) for m in g.members], "real_path_display": str(g.real), "status": s["status"]}
        for g, s in zip(groups, read)]}

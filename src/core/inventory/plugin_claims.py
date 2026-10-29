
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.inventory import plugin_stores as stores
from src.core.inventory import plugin_units as units
from src.core.inventory.file_claims import claimed_item_ids
from src.core.inventory.file_trace import measured_artifact
from src.core.inventory.locations import Locations
from src.core.inventory.model import KIND_DIR, KIND_FILE, REPORT, SCOPE_PROJECT, Artifact, Inventory
from src.core.inventory.scope import project_scope
from src.core.work import tables as work_tables
from src.cplugs.sdk.computer import local_computer

logger = structlog.get_logger()

_CARRIED = "carried"
SCOPE_TASK, SCOPE_SESSION_KEY, SCOPE_PROJECT_KEY, SCOPE_INSTALL = "task_item_id", "session_uuid", "project", "install"
_NOISE_SUFFIXES: Tuple[str, ...] = ("-wal", "-shm", "-journal", ".lock", ".tmp")


def owner_keys(inv: Inventory, conn: sqlite3.Connection) -> units.OwnerKeys:
    if inv.scope == SCOPE_PROJECT and inv.project is not None:
        sessions = frozenset(c.session.session_uuid for c in inv.children if c.session is not None)
        keys = frozenset(str(k) for k in (inv.project.project_id, inv.project.uid) if k not in (None, ""))
        items = frozenset(claimed_item_ids(conn, project_scope(inv.project)))
        return units.OwnerKeys(SCOPE_PROJECT, sessions, keys, items, inv.project.list_key,
                               known_item_ids=_all_item_ids(conn), here=local_computer())
    sessions = frozenset({inv.session.session_uuid}) if inv.session is not None else frozenset()
    return units.OwnerKeys("session", sessions)


def _all_item_ids(conn: sqlite3.Connection) -> frozenset:
    try:
        return frozenset(int(r[0]) for r in conn.execute(f"SELECT id FROM {work_tables.ITEMS}"))
    except sqlite3.Error as exc:
        logger.warning("plugin_items_unreadable", error=str(exc))
        return frozenset()


def _base_locator(store: stores.PluginStore) -> Dict[str, Any]:
    return {"plugin": store.plugin_id, "data": store.decl.id, "decl_kind": store.decl.kind, "scope_by": store.decl.scope_by,
            "policy": store.policy_json(), "backup": store.decl.policy.backup, "enabled": store.enabled}


def _carries(store: stores.PluginStore) -> bool:
    pol = store.decl.policy
    return _CARRIED in (pol.own, pol.share)


def _listed(store: stores.PluginStore, locator: Dict[str, Any], what: str, reason: str) -> Artifact:
    kind = KIND_FILE if store.decl.kind != "folder" else KIND_DIR
    return Artifact(store=store.key, kind=kind, what=what, count=0, action=REPORT, reason=reason, locator=locator)


def _owner_keys_for(store: stores.PluginStore, owner: units.OwnerKeys) -> set:
    if store.decl.scope_by == SCOPE_SESSION_KEY:
        return set(owner.session_uuids)
    return set(owner.project_keys) if owner.kind == SCOPE_PROJECT else set()


def _scoped_units(store: stores.PluginStore, root: Path, owner: units.OwnerKeys,
                  siblings: Dict[str, List[units.TaskLink]], problems: List[str]) -> Tuple[List[units.Unit], int]:
    """The units of a carried folder store this scope owns, and the count it leaves out. Output: (units, out of scope).

    Inputs: ...; problems (collects a sentence per folder that could not be listed).
    """
    if store.decl.scope_by == SCOPE_TASK:
        return units.task_units(root, siblings, owner, problems)
    return units.owner_units(root, _owner_keys_for(store, owner))


def _measured(store: stores.PluginStore, root: Path, chosen: List[units.Unit], locator: Dict[str, Any], blockers: List[str]) -> Artifact:
    count = size = 0
    kept: List[units.Unit] = []
    for unit in chosen:
        art = measured_artifact(store.key, str(root / unit.rel), root, REPORT, "", blockers)
        if art is not None:
            kept.append(unit)
            count, size = count + art.count, size + art.size
    locator = {**locator, "root": str(root), "units": [u.as_json() for u in kept]}
    return Artifact(store=store.key, kind=KIND_DIR, what=str(root), count=count, size=size, action=REPORT,
                    reason=store.decl.policy.reason, locator=locator)


def store_artifact(store: stores.PluginStore, owner: units.OwnerKeys, siblings: Dict[str, List[units.TaskLink]],
                   blockers: List[str], unsafe: Optional[str] = None) -> Artifact:
    locator = _base_locator(store)
    reason = store.decl.policy.reason
    if store.location is None:
        return _listed(store, {**locator, "unset": store.setting}, f"{store.key} (setting {store.setting} is not set)", reason)
    what = str(store.location)
    locator["path"] = what
    if store.decl.scope_by == SCOPE_INSTALL:
        return _listed(store, {**locator, "install_scoped": True}, what, reason)
    if not _carries(store):
        return _listed(store, locator, what, reason)
    if store.decl.kind != "folder":
        return _listed(store, {**locator, "unscopable": True}, what, reason)
    if unsafe:
        blockers.append(unsafe)
        return _listed(store, {**locator, "units": [], "root": what}, what, reason)
    if not os.path.isdir(store.location) or os.path.islink(store.location):
        return _listed(store, {**locator, "units": [], "root": what}, what, reason)
    chosen, left = _scoped_units(store, store.location, owner, siblings, blockers)
    return _measured(store, store.location, chosen, {**locator, "out_of_scope": left}, blockers)


def _unsafe(store: stores.PluginStore, locations: Locations) -> Optional[str]:
    return stores.root_problem(store, locations) if _carries(store) and store.decl.root_setting else None


def _task_siblings(plugin_stores: List[stores.PluginStore]) -> Dict[str, List[units.TaskLink]]:
    boards: List[units.Board] = []
    for store in plugin_stores:
        if store.decl.scope_by == SCOPE_TASK and store.decl.kind == "folder" and store.location is not None and os.path.isdir(store.location):
            boards += units.find_boards(store.location)
    return units.slug_index(boards)


def _data_children(folder: Path) -> List[Path]:
    try:
        names = sorted(os.listdir(folder))
    except OSError as exc:
        if not isinstance(exc, FileNotFoundError):
            logger.warning("plugin_folder_unreadable", path=str(folder), error=type(exc).__name__)
        return []
    return [folder / n for n in names if not n.startswith(".") and not n.endswith(_NOISE_SUFFIXES) and not os.path.islink(folder / n)]


def _holds_data(path: Path, state: Path, patterns: List[str], suffixes: Tuple[str, ...]) -> bool:
    from src.core.inventory import state_files  # noqa: PLC0415

    if not path.is_dir():
        return path.name.endswith(suffixes)
    for here, dirnames, filenames in os.walk(path):
        rel_here = Path(here).relative_to(state).as_posix()
        dirnames[:] = [d for d in dirnames if not state_files.accounted(f"{rel_here}/{d}", patterns) and not os.path.islink(os.path.join(here, d))]
        if any(f.endswith(suffixes) and not state_files.accounted(f"{rel_here}/{f}", patterns) for f in filenames):
            return True
    return False


def undeclared_artifacts(locations: Locations) -> List[Artifact]:
    from src.core.inventory import registry, state_files  # noqa: PLC0415

    patterns = state_files.core_patterns(registry.book())
    out: List[Artifact] = []
    for manifest in stores.undeclared_manifests(locations):
        folder = Path(locations.state_dir) / stores.PLUGINS_DIR / manifest.id
        for path in _data_children(folder):
            rel = path.relative_to(Path(locations.state_dir)).as_posix()
            if state_files.accounted(rel, patterns) or not _holds_data(path, Path(locations.state_dir), patterns, state_files.DATA_SUFFIXES):
                continue
            kind = KIND_DIR if path.is_dir() else KIND_FILE
            out.append(Artifact(store=f"{manifest.id}.undeclared", kind=kind, what=str(path), count=0, action=REPORT,
                                reason=f"the {manifest.id} plugin declares no data in its carnivore.json and keeps this",
                                locator={"plugin": manifest.id, "undeclared": True, "path": str(path)}))
    return out


def add_plugin_artifacts(inv: Inventory, conn: sqlite3.Connection, locations: Locations) -> Inventory:
    owner = owner_keys(inv, conn)
    declared = stores.declared_stores(locations)
    by_plugin: Dict[str, List[stores.PluginStore]] = {}
    for store in declared:
        by_plugin.setdefault(store.plugin_id, []).append(store)
    blockers: List[str] = []
    for group in by_plugin.values():
        siblings = _task_siblings(group) if any(s.decl.scope_by == SCOPE_TASK and _carries(s) for s in group) else {}
        inv.artifacts += [store_artifact(s, owner, siblings, blockers, _unsafe(s, locations)) for s in group]
    inv.artifacts += undeclared_artifacts(locations)
    inv.blockers += blockers
    return inv

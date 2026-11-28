"""The one-time carry of a renamed plugin's stored entry and install-ledger rows to its new id (#3260 slice S2), plus its reverse switch.

``Manifest.renamed_from`` (slice S1) names the one old id a plugin used to have. What the owner stored under the old id (the on/off
switch, the grants the owner gave, the settings, the revision) lives in the cplugs state file; the install ledger carries two text
columns keyed by the id (``name`` ``cplug-<id>`` and ``item_id`` ``<publisher>/<id>``). Without a carry, a renamed plugin would start
as a stranger: off, ungranted, default settings (Joe (ccsliinc), 2026-11-22, Task Manager rename: the same plugin keeps its state).

Rules, in order of importance:

- NEVER OVER A CHOICE: the entry is copied only while the new id has none, so a second boot, or an owner who already answered, is never
  touched. ONE-SHOT: once a pair has been carried (or the owner had already answered under the new id) that is recorded in
  ``cplugs/renamed-carried.json``, and a recorded pair is never copied again, even after the owner turns the plugin off and purges it (an
  absent new entry is then an answer, not a gap; without the record the stale old snapshot, grants included, would come back on the next
  boot). The record is its own file because every owner write rebuilds the state document from its ``cplugs`` map alone. The copy is the whole entry, grants INCLUDED (unlike ``plugin_fold.py``: that moves one plugin's settings into another plugin;
  this is the same plugin under a new name).
- THE OLD ENTRY STAYS where it is, byte for byte, so an older build that reads the old id still finds it (rollback).
- Written through the one registry writer, :func:`registry_store.commit`, which reads inside the lock and never takes a base from the caller.
  An unreadable or busy store writes nothing, logs at error level and is retried on the next boot.
- The ledger relabel is ONE transaction of plain UPDATEs (no DDL). A row whose new label is already taken is skipped, never merged, and
  logged at info level as ``cplug_renamed_ledger_skipped`` with its scope (after a rollback the older build re-adopts the old row on every
  boot, so the skip repeats; two rows for one plugin are harmless, so it is not a warning).

REVERSE SWITCH (Joe (ccsliinc), 2026-11-22, answer 11: rolling back to an older build loses what changed after the move; acceptable "with a
reverse switch"): an older build reads the old entry whether or not the new one exists, so the switch does not change what it reads. What it
does is let the NEXT upgrade carry again: :func:`revert` removes the copied entry and its record ONLY while the owner's choices on it
(``enabled``, ``grants``, ``settings``) still equal the old entry's, so a setting the owner changed on the new id is never deleted, and a
bookkeeping bump (revision, digest, timestamp) by a boot step does not block it. RUN IT BEFORE LAUNCHING THE OLDER BUILD: once that build
changes the old entry, the copy no longer matches and is kept, and the rollback-period changes are not carried at the next upgrade. With the
app stopped: ``python3 -m src.plugins.host.renamed_entry --revert [--state-dir DIR] [--pair OLD=NEW]``. The install ledger is not undone: an
older build re-adopts ``cplug-<old>`` next to the relabeled row, which is harmless (two rows, one plugin). The command REFUSES (exit 1) while
the app's port answers: a running app would re-create the new entry from scratch on the next owner write, after its record was dropped.

The switch also FORGETS a recorded pair whose new entry is absent while its old entry is present (the plugin store was restored from a
backup taken before the rename; ``cplugs/renamed-carried.json`` is not in that backup), so the next boot carries again instead of
skipping the pair forever. A pair with no old entry either (a purge dropped both) stays recorded, so nothing comes back.
"""

from __future__ import annotations

import argparse
import copy
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import structlog

from src.core import db
from src.core.json_artifact import atomic_write_json, read_for_update
from src.core.skills import kinds
from src.plugins.host import registry_store
from src.plugins.host.app_probe import app_answers
from src.plugins.host.ledger_names import NAME_PREFIX

logger = structlog.get_logger()

LEDGER_NAME_PREFIX = NAME_PREFIX
LEDGER_KIND = kinds.KIND_CPLUG
CARRIED_FILE = "renamed-carried.json"
CARRIED_VERSION = 1
CHOICE_KEYS = ("enabled", "grants", "settings")


@dataclass
class RenameOutcome:

    copied: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    forgotten: List[str] = field(default_factory=list)
    relabeled: int = 0
    failed: bool = False


def configured_renames() -> Dict[str, str]:
    from src.plugins.host import runtime

    return {d.manifest.renamed_from: d.id for d in runtime.definitions() if d.manifest.renamed_from}


_STATE_FIELDS = ("enabled", "grants", "settings", "revision", "digest", "updated_at", "ui_slot_grants", "state_extra")


def _is_stored_entry(entry: Any) -> bool:
    return isinstance(entry, dict) and entry.get("unstored") is not True and any(k in entry for k in _STATE_FIELDS)


def _strip_state_entry(items: Dict[str, Any], plugin_id: str) -> None:
    entry = items.get(plugin_id)
    if not isinstance(entry, dict):
        return
    if "install_uuid" in entry or "sideload_record" in entry:
        for field_name in _STATE_FIELDS:
            entry.pop(field_name, None)
        entry.pop("state_raw", None)
        entry["unstored"] = True
    else:
        del items[plugin_id]


def carried_path(state_dir: Path) -> Path:
    return registry_store.cplugs_dir(state_dir) / CARRIED_FILE


def _read_carried(state_dir: Path) -> Dict[str, str]:
    carried = read_for_update(carried_path(state_dir), log_event="cplug_renamed_carried_unreadable").get("carried")
    return {str(o): str(n) for o, n in carried.items()} if isinstance(carried, dict) else {}


def is_recorded(state_dir: Path, old: str, new: str) -> bool:
    return _read_carried(state_dir).get(old) == new


def _write_carried(state_dir: Path, carried: Mapping[str, str]) -> bool:
    return atomic_write_json(carried_path(state_dir), {"version": CARRIED_VERSION, "carried": dict(carried)}, log_event="cplug_renamed_carried_write_failed")


def _record_carried(state_dir: Path, decided: Mapping[str, str]) -> None:
    if decided and not _write_carried(state_dir, {**_read_carried(state_dir), **decided}):
        logger.error("cplug_renamed_entry_failed", step="record", error_type="WriteFailed", error="the carried record could not be written")


def _copy_entries(state_dir: Path, renames: Mapping[str, str]) -> List[str]:
    carried = _read_carried(state_dir)
    todo = {old: new for old, new in renames.items() if carried.get(old) != new}

    def mutate(doc: Dict[str, Any]) -> Tuple[List[str], Dict[str, str]]:
        items = doc.setdefault("items", {})
        copied: List[str] = []
        decided: Dict[str, str] = {}
        for old, new in todo.items():
            entry = items.get(old)
            if not _is_stored_entry(entry):
                continue
            decided[old] = new
            if not _is_stored_entry(items.get(new)):
                copied_state = {k: copy.deepcopy(v) for k, v in entry.items() if k in _STATE_FIELDS}
                existing_new = items.get(new)
                if isinstance(existing_new, dict):
                    existing_new.pop("unstored", None)
                    existing_new.update(copied_state)
                else:
                    items[new] = {"kind": registry_store.KIND_FEATURE, **copied_state}
                copied.append(old)
        return copied, decided

    if not todo or not registry_store.registry_path(state_dir).is_file():
        return []
    copied, decided = registry_store.commit(state_dir, mutate, log_event="cplug_renamed_entry_write_failed")
    _record_carried(state_dir, decided)
    return copied


def _relabel_ledger(state_dir: Path, renames: Mapping[str, str]) -> int:
    path = db.db_path_for(state_dir)
    if not path.exists():
        return 0
    with closing(db.connect(path, create=False)) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='installed_items'").fetchone() is None:
            return 0
        conn.execute("BEGIN IMMEDIATE")
        try:
            changed = sum(_relabel_one(conn, old, new) for old, new in renames.items())
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return changed


def _relabel_one(conn: sqlite3.Connection, old: str, new: str) -> int:
    rows = conn.execute("SELECT install_id, item_id, scope, project_path FROM installed_items WHERE kind = ? AND name = ?",
                        (LEDGER_KIND, LEDGER_NAME_PREFIX + old)).fetchall()
    changed = 0
    for row in rows:
        publisher, _, tail = row["item_id"].rpartition("/")
        new_item_id = f"{publisher}/{new}"
        if tail != old:
            continue
        if _taken(conn, row, new_item_id, LEDGER_NAME_PREFIX + new):
            logger.info("cplug_renamed_ledger_skipped", old=old, new=new, scope=row["scope"], reason="new label already taken")
            continue
        conn.execute("UPDATE installed_items SET item_id = ?, name = ?, revision = revision + 1 WHERE install_id = ?",
                     (new_item_id, LEDGER_NAME_PREFIX + new, row["install_id"]))
        changed += 1
    return changed


def _taken(conn: sqlite3.Connection, row: sqlite3.Row, item_id: str, name: str) -> bool:
    return conn.execute("SELECT 1 FROM installed_items WHERE scope = ? AND project_path = ? AND (item_id = ? OR name = ?)",
                        (row["scope"], row["project_path"], item_id, name)).fetchone() is not None


def migrate(state_dir: Path, renames: Optional[Mapping[str, str]] = None) -> RenameOutcome:
    pairs = dict(configured_renames() if renames is None else renames)
    outcome = RenameOutcome()
    if not pairs:
        return outcome
    try:
        outcome.copied = _copy_entries(state_dir, pairs)
    except OSError as exc:
        outcome.failed = True
        logger.error("cplug_renamed_entry_failed", step="entry", error_type=type(exc).__name__, error=str(exc)[:200])
    try:
        outcome.relabeled = _relabel_ledger(state_dir, pairs)
    except (sqlite3.Error, db.DatastoreUnreadableError) as exc:
        outcome.failed = True
        logger.error("cplug_renamed_entry_failed", step="ledger", error_type=type(exc).__name__, error=str(exc)[:200])
    for old in outcome.copied:
        logger.info("cplug_renamed_entry_copied", old=old, new=pairs[old])
    if outcome.relabeled:
        logger.info("cplug_renamed_ledger_relabeled", rows=outcome.relabeled, renames=sorted(f"{o}>{n}" for o, n in pairs.items()))
    return outcome


def _choices(entry: Any) -> Dict[str, Any]:
    return {k: entry.get(k) for k in CHOICE_KEYS} if isinstance(entry, dict) else {}


def _forget_carried(state_dir: Path, outcome: RenameOutcome, olds: Sequence[str]) -> None:
    try:
        carried = _read_carried(state_dir)
        remaining = {o: n for o, n in carried.items() if o not in olds}
        if remaining != carried and not _write_carried(state_dir, remaining):
            outcome.failed = True
    except OSError as exc:
        outcome.failed = True
        logger.error("cplug_renamed_entry_failed", step="revert_record", error_type=type(exc).__name__, error=str(exc)[:200])


def forget_old_entries(state_dir: Path, new_id: str, renames: Optional[Mapping[str, str]] = None) -> List[str]:
    olds = [o for o, n in (configured_renames() if renames is None else renames).items() if n == new_id]

    def mutate(doc: Dict[str, Any]) -> List[str]:
        items = doc.setdefault("items", {})
        dropped: List[str] = []
        for old in olds:
            if _is_stored_entry(items.get(old)):
                _strip_state_entry(items, old)
                dropped.append(old)
        return dropped

    if not olds or not registry_store.registry_path(state_dir).is_file():
        return []
    try:
        return registry_store.commit(state_dir, mutate, log_event="cplug_renamed_entry_write_failed")
    except OSError as exc:
        logger.error("cplug_renamed_entry_failed", step="forget_old", error_type=type(exc).__name__, error=str(exc)[:200])
        return []


def _restored_without_copy(state_dir: Path, pairs: Mapping[str, str], items: Mapping[str, Any]) -> List[str]:
    carried = _read_carried(state_dir)
    return [old for old, new in pairs.items() if carried.get(old) == new and not _is_stored_entry(items.get(new)) and _is_stored_entry(items.get(old))]


def revert(state_dir: Path, renames: Optional[Mapping[str, str]] = None) -> RenameOutcome:
    pairs = dict(configured_renames() if renames is None else renames)
    outcome = RenameOutcome()

    def mutate(doc: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        items = doc.setdefault("items", {})
        forgotten = _restored_without_copy(state_dir, pairs, items)
        removed: List[str] = []
        for old, new in pairs.items():
            if not _is_stored_entry(items.get(new)) or not _is_stored_entry(items.get(old)):
                continue
            if _choices(items[new]) == _choices(items[old]):
                _strip_state_entry(items, new)
                removed.append(old)
            else:
                logger.warning("cplug_renamed_entry_revert_kept", old=old, new=new, reason="changed since the copy")
        return removed, forgotten

    if not pairs or not registry_store.registry_path(state_dir).is_file():
        return outcome
    try:
        outcome.removed, outcome.forgotten = registry_store.commit(state_dir, mutate, log_event="cplug_renamed_entry_write_failed")
    except OSError as exc:
        outcome.failed = True
        logger.error("cplug_renamed_entry_failed", step="revert", error_type=type(exc).__name__, error=str(exc)[:200])
    if outcome.removed or outcome.forgotten:
        _forget_carried(state_dir, outcome, [*outcome.removed, *outcome.forgotten])
    for old in outcome.removed:
        logger.info("cplug_renamed_entry_reverted", old=old, new=pairs[old])
    for old in outcome.forgotten:
        logger.info("cplug_renamed_entry_record_forgotten", old=old, new=pairs[old], reason="new entry absent, old entry present")
    return outcome


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="renamed_entry", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--revert", action="store_true", required=True, help="remove each copied new-id entry that is unchanged since the copy")
    parser.add_argument("--state-dir", type=Path, default=None, help="the app state directory (default: the live one)")
    parser.add_argument("--pair", action="append", default=[], metavar="OLD=NEW", help="a rename; default: every renamed_from in the manifests")
    parser.add_argument("--port", type=int, default=None, help="the app's port to probe (default: the configured one)")
    args = parser.parse_args(argv)
    pairs = dict(p.split("=", 1) for p in args.pair if "=" in p) if args.pair else None
    if args.pair and (pairs is None or len(pairs) != len(args.pair)):
        parser.error("--pair takes OLD=NEW")
    from src.config import settings

    state_dir = args.state_dir if args.state_dir is not None else settings.get_state_dir()
    port = args.port if args.port is not None else settings.port
    if app_answers(port):
        print(f"refused: the app is running (port {port} answers); stop it first")
        return 1
    outcome = revert(state_dir, pairs)
    print(f"removed copies for: {', '.join(outcome.removed) or 'none'}")
    if outcome.forgotten:
        print(f"forgot carried records for: {', '.join(outcome.forgotten)}")
    return 1 if outcome.failed else 0


if __name__ == "__main__":
    sys.exit(main())

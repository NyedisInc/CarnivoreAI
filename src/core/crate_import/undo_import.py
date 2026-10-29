
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core import config_writer, resource_push, ui_preferences
from src.core.account_switch import session_pin
from src.core.crate_import import apply as ap
from src.core.crate_import import entries_in, journal_in, ledger, row_undo, undo
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.model import IMPORT_ID_RE
from src.core.db import connect, db_path_for, transaction
from src.core.project_move.apply import MoveBusy, one_move_at_a_time
from src.core.project_move.paths import PathMapping
from src.core.resource_push import topics as resource_topics
from src.core.sessions import theme_dotfile
from src.core.inventory.registry_side import AUTOMATIONS, BOOKMARKS
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

U_NOT_FOUND, U_NOT_FINISHED, U_NO_RECORD, U_LATER_IMPORT = "import_not_found", "import_not_finished", "no_undo_record", "later_import"
U_INCOMPLETE, U_UNREADABLE, U_PLUGIN_OFF, U_BUSY, U_ALREADY = "record_incomplete", "database_unreadable", "plugin_unavailable", "busy", "already_undone"
_FINISHED = (ap.PHASE_DONE, ap.PHASE_DONE_WARNINGS)


@dataclass
class UndoPlan:

    import_id: str
    blockers: List[Dict[str, str]] = field(default_factory=list)
    rows: Optional[row_undo.RowsPlan] = None
    entries: List[Dict[str, Any]] = field(default_factory=list)
    journal: Optional[Dict[str, Any]] = None
    record: Dict[str, Any] = field(default_factory=dict)
    project_id: Optional[int] = None

    @property
    def ok(self) -> bool:
        return not self.blockers

    def as_json(self) -> Dict[str, Any]:
        stores = self.rows.stores if self.rows else []
        return {"import_id": self.import_id, "ok": self.ok, "blockers": list(self.blockers),
                "rows_to_remove": sum(s.count() for s in stores), "rows_to_put_back": sum(len(v) for s in stores for v in s.restores.values()),
                "kept": [k for s in stores for k in s.kept]}


@dataclass
class UndoReport:

    import_id: str
    rows: Dict[str, int] = field(default_factory=dict)
    files: undo.UndoReport = field(default_factory=undo.UndoReport)
    entries_removed: List[str] = field(default_factory=list)
    kept: List[Dict[str, str]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def as_json(self) -> Dict[str, Any]:
        return {"import_id": self.import_id, "rows": dict(self.rows), "files_removed": self.files.files_removed, "folders_removed": len(self.files.removed_dirs),
                "entries_removed": list(self.entries_removed), "errors": list(self.errors),
                "kept": [*self.kept, *({"what": p, "why": "changed since the import, or not the import's"} for p in self.files.kept if p)],
                "file_errors": list(self.files.errors)}


class UndoRefused(Exception):

    def __init__(self, blockers: List[Dict[str, str]]) -> None:
        super().__init__("; ".join(f"{b['code']}: {b['detail']}" for b in blockers))
        self.blockers = blockers


def _blocker(code: str, detail: str) -> Dict[str, str]:
    return {"code": code, "detail": detail}


def _file_blockers(log: List[Dict[str, Any]], env: ImportEnv) -> List[Dict[str, str]]:
    from src.core.deepsearch import fallback_hook as fb

    out: List[Dict[str, str]] = []
    if any(e.get("op") == undo.OP_VAULT for e in log) and not any(hasattr(s, "remove_adopted") for s in fb.sources()):
        out.append(_blocker(U_PLUGIN_OFF, "the restore filed backup points and the backup plugin is off; switch it on and undo again"))
    for e in log:
        store = e.get("store")
        if isinstance(store, list) and len(store) == 2 and os.path.lexists(str(e.get("path", ""))) and env.plugin_homes(str(store[0]), str(store[1])) is None:
            out.append(_blocker(U_PLUGIN_OFF, f"the restore placed files of {store[0]}/{store[1]} and that store has no folder now; switch the plugin on and undo again"))
            break
    return out


def plan_undo(env: ImportEnv, import_id: str, log: List[Dict[str, Any]]) -> UndoPlan:
    plan = UndoPlan(import_id)
    if not IMPORT_ID_RE.match(import_id):
        plan.blockers.append(_blocker(U_NOT_FOUND, "that is not an import id"))
        return plan
    conn = env.connect()
    try:
        entry = ledger.read_entry(conn, import_id)
        record = ledger.read_undo(conn, import_id)
        later = [e["import_id"] for e in ledger.all_entries(conn) if e["import_id"] > import_id and e.get("phase") != ledger.PHASE_UNDONE
                 and e.get("source_install") == (entry or {}).get("source_install")]
    finally:
        conn.close()
    if entry is None:
        plan.blockers.append(_blocker(U_NOT_FOUND, "the database has no record of this import"))
    elif entry.get("phase") == ledger.PHASE_UNDONE:
        plan.blockers.append(_blocker(U_ALREADY, "this restore was already undone"))
    elif entry.get("phase") not in _FINISHED:
        plan.blockers.append(_blocker(U_NOT_FINISHED, "this restore did not finish; restoring the same crate again finishes it"))
    elif record is None:
        plan.blockers.append(_blocker(U_NO_RECORD, "this restore was made before undo existed, so there is no record of the rows it wrote"))
    if later:
        plan.blockers.append(_blocker(U_LATER_IMPORT, f"a later restore from the same source followed this one ({later[0]}); undo that one first"))
    if plan.blockers or record is None:
        return plan
    plan.record = record
    plan.project_id = ((entry or {}).get("created") or {}).get("project", {}).get("project_id")
    plan.entries, plan.journal = list(record.get("entries") or []), record.get("journal")
    plan.rows = row_undo.plan(Path(env.state), record)
    plan.blockers += [_blocker(code, detail) for code, detail in plan.rows.blockers]
    plan.blockers += _file_blockers(log, env)
    return plan


def _remove_member(root: Dict[str, Any], path: List[Any], value: Any) -> bool:
    chain: List[Any] = [root]
    for step in path[:-1]:
        child = chain[-1].get(step) if isinstance(chain[-1], dict) else None
        if not isinstance(child, (dict, list)):
            return False
        chain.append(child)
    node, last = chain[-1], path[-1]
    if isinstance(last, int) and isinstance(node, list) and value in node:
        node.remove(value)
    elif isinstance(last, str) and isinstance(node, dict) and node.get(last) == value:
        del node[last]
    else:
        return False
    for depth in range(len(chain) - 1, 0, -1):
        if not chain[depth]:
            del chain[depth - 1][path[depth - 1]]
    return True


def _undo_drawer(config_path: Path, members: List[Dict[str, Any]]) -> int:
    done = {"n": 0}

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        import copy

        stored = ui_preferences.read_block(config)["values"].get(entries_in.ARRANGEMENT)
        merged = copy.deepcopy(stored) if isinstance(stored, dict) else None
        if merged is None:
            return None
        done["n"] = sum(1 for m in members if _remove_member(merged, list(m["path"]), m["value"]))
        if not done["n"]:
            return None
        cleared = [k for k in ui_preferences.CARRIED_DRAWER_KEYS if k not in merged and stored.get(k) is not None]
        for key in cleared:
            merged[key] = None
        new_config, _block, moved = ui_preferences.apply_changes(config, ui_preferences.validate_changes({entries_in.ARRANGEMENT: merged}))
        if not moved:
            return None
        stored_now = ui_preferences.read_block(new_config)["values"].get(entries_in.ARRANGEMENT)
        for key in cleared:
            if isinstance(stored_now, dict) and stored_now.get(key) is None:
                stored_now.pop(key, None)
        return new_config

    config_writer.commit(config_path, mutate)
    return done["n"]


def undo_entries(env: ImportEnv, records: List[Dict[str, Any]], journal: Optional[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    drawer = [m for r in records if r.get("kind") == entries_in.UNDO_DRAWER for m in r.get("members") or []]
    if drawer and env.config_path is not None:
        out.append(f"{_undo_drawer(env.config_path, drawer)} drawer arrangement member(s)")
    for r in records:
        if r.get("kind") == entries_in.UNDO_PIN and env.config_path is not None and session_pin.pin_for(env.config_path, r["uuid"]) == r["account"]:
            session_pin.apply_choice(env.config_path, r["uuid"], r["account"], pinned=False)
            out.append(f"account pin of {r['uuid']}")
        elif r.get("kind") == entries_in.UNDO_THEME and Path(r["folder"]).is_dir() and theme_dotfile.read_project_theme(r["folder"]) == r["text"]:
            theme_dotfile.write_project_theme(r["folder"], None)
            out.append(f"{theme_dotfile.DOTFILE_NAME} in {r['folder']}")
    if journal and journal.get("rules"):
        inverse = PathMapping.of([(new, old) for old, new in journal["rules"]])
        back = journal_in.rebase_for_import(Path(env.state), inverse, journal.get("uuids") or [])
        if back.state == journal_in.JOURNAL_UPDATED:
            out.append(f"{back.rewritten} reboot journal path(s)")
    return out


def _notify(plan: UndoPlan) -> None:
    topics = [resource_topics.PROJECTS, "cplug.huddle.list:all"]
    if plan.project_id is not None:
        topics.append(f"cplug.huddle.list:{plan.project_id}")
    stores = (plan.record.get("stores") or {}).keys()
    topics += [t for store, t in ((AUTOMATIONS, resource_topics.AUTOMATIONS), (BOOKMARKS, resource_topics.BOOKMARKS)) if store in stores]
    for topic in topics:
        try:
            resource_push.notify(topic)
        except (RuntimeError, ValueError) as exc:
            logger.warning("crate_import_undo_notify_failed", topic=topic, error=str(exc))


def run_undo(env: ImportEnv, import_id: str, log: List[Dict[str, Any]]) -> UndoReport:
    try:
        with one_move_at_a_time():
            plan = plan_undo(env, import_id, log)
            if not plan.ok or plan.rows is None:
                raise UndoRefused(plan.blockers)
            report = UndoReport(import_id)
            done = row_undo.apply(Path(env.state), plan.record, plan.rows)
            report.rows, report.kept = {"deleted": done.deleted, "restored": done.restored, "reverted": done.reverted}, done.kept
            try:
                report.entries_removed = undo_entries(env, plan.entries, plan.journal)
            except (ValueError, OSError) as exc:
                logger.warning("crate_import_undo_entries_failed", import_id=import_id, error_type=type(exc).__name__)
                report.errors.append(f"config and journal: {type(exc).__name__}")
            report.files = ap.recover_files(log, env, import_id)
            conn = connect(db_path_for(Path(env.state)), create=False)
            try:
                with transaction(conn):
                    ledger.mark_undone(conn, import_id, utc_now())
            finally:
                conn.close()
            _notify(plan)
            logger.info("crate_import_undone", import_id=import_id, deleted=done.deleted, restored=done.restored, kept=len(report.kept))
            return report
    except MoveBusy as exc:
        raise UndoRefused([_blocker(U_BUSY, str(exc))]) from exc

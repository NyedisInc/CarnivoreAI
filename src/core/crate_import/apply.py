
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core import resource_push
from src.core.crate_format.reader import CrateReader
from src.core.crate_import import analysis as an
from src.core.crate_import import (
    backups_apply, backups_folder_apply, cleanup_apply, entries_in, files_apply, files_place, guard, project_files_place, hooks as hk, journal_in, ledger, plan as plan_mod, plugin_data_in, policy, rows_history,
    rows_identity, rows_side,
    rows_work, rows_write, row_journal, task_files_in, undo, verify_after,
)
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.idmap import IdMap
from src.core.crate_import.model import (
    PHASE_DONE, PHASE_DONE_WARNINGS, PHASE_ROWS_COMMITTED, Collector, ImportFailed, ImportRefused, ImportRequest,
)
from src.core.db import connect, db_path_for, transaction
from src.core.inventory.model import MAIN_STORE
from src.core.project_move.apply import MoveBusy, one_move_at_a_time
from src.core.resource_push import topics as resource_topics
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

STATE_DONE = "done"
STATE_DONE_WARNINGS = "done_with_warnings"
STATE_NOOP = "noop"
E_DB = "database_failed"
W_JOURNAL_NOT_REBASED = "journal_not_rebased"


@dataclass
class ImportReceipt:

    import_id: str
    state: str
    bundle_id: str
    crate_sha256: str
    provenance: str
    project: Dict[str, Any]
    files: Dict[str, Any]
    rows: Dict[str, Any]
    sessions: List[Dict[str, Any]] = field(default_factory=list)
    conversations: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, str]] = field(default_factory=list)
    not_restored: List[Dict[str, str]] = field(default_factory=list)
    checks: Dict[str, Any] = field(default_factory=dict)
    journal: Dict[str, Any] = field(default_factory=dict)
    task_files: Dict[str, Any] = field(default_factory=dict)
    entries: Dict[str, Any] = field(default_factory=dict)
    plugin_data: Dict[str, Any] = field(default_factory=dict)
    project_files: Dict[str, Any] = field(default_factory=dict)
    cleanup: Dict[str, Any] = field(default_factory=dict)
    backups: Dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _changed(placed: files_apply.PlacedFiles, ctx: rows_write.WriteCtx, project: Dict[str, Any]) -> bool:
    return bool(placed.written or placed.project_written or placed.backups.get("adopted") or project["created"] or any(c.inserted for c in ctx.counts.values()))


def _prior_map(conn: sqlite3.Connection, source_install: Optional[str]) -> IdMap:
    merged: Dict[str, Dict[str, Any]] = {}
    for entry in ledger.entries_from(conn, source_install or ""):
        for table, mapping in (entry.get("key_map") or {}).items():
            merged.setdefault(table, {}).update(mapping)
    return IdMap(merged)


def imported_uuids(a: an.Analysis) -> List[str]:
    return [s["session_uuid"] for s in restored_sessions(a)]


def restored_sessions(a: an.Analysis) -> List[Dict[str, Any]]:
    plan = a.sessions
    return [{"session_uuid": plan.translate[u] if u in plan.reminted else u, "asleep": True, "conversation_id": conv}
            for u, conv in a.crate_sessions if u not in plan.skip_sessions and (u not in plan.translate or u in plan.reminted)]


def _measure_again(env: ImportEnv, a: an.Analysis) -> guard.LiveFacts:
    conn, col = env.connect(), Collector()
    try:
        first_dir = a.crate_project.working_dirs[0] if a.crate_project.working_dirs else a.crate_project.root
        facts = guard.measure(env, conn, a.crate_sessions, [c.id for c in a.manifest.conversations], a.request.new_root or first_dir, col)
    finally:
        conn.close()
    if col.blockers:
        first = col.blockers[0]
        raise ImportRefused(first.code, first.detail)
    return facts


def _commit_rows(env: ImportEnv, a: an.Analysis, import_id: str, placed: files_apply.PlacedFiles, hooks: hk.ApplyHooks,
                 now: Optional[str]) -> tuple:
    hooks.phase(hk.PHASE_ROWS)
    conn = connect(db_path_for(Path(env.state)), create=False)
    try:
        with transaction(conn):
            try:
                tracked = row_journal.start(conn)
            except row_journal.JournalError as exc:
                raise ImportFailed("journal_failed", f"the rows cannot be recorded for an undo: {exc}", rolled_back=True) from exc
            ctx = rows_write.WriteCtx(conn, _prior_map(conn, a.source_install), a.prov.own, a.col,
                                      files=task_files_in.file_home(Path(env.state), lambda entry: files_apply.record_undo(hooks, placed, entry),
                                                              task_files_in.task_roots(env)))
            for old, new in a.sessions.translate.items():
                ctx.idmap.put(rows_identity.SESSION_UUIDS, old, new)
            sanitized = a.rows.sanitized if a.rows else {}
            deferred = rows_identity.write_companies(ctx, sanitized.get(rows_identity.COMPANIES, []))
            project = rows_identity.write_project(ctx, a, now)
            rows_identity.finish_companies(ctx, deferred)
            rows_identity.write_sessions(ctx, a, project["project_id"])
            for key in policy.APPLY_ORDER:
                if key not in (rows_identity.COMPANIES, rows_identity.PROJECTS, rows_identity.SESSIONS):
                    rows_write.write_generic(ctx, key, sanitized.get(key, []))
            rows_work.write_work(ctx, sanitized, _restored_group_name(a))
            rows_history.write_history(ctx, sanitized)
            changed = _changed(placed, ctx, project)
            if changed:
                ledger.write_entry(conn, import_id, {
                    "source_install": a.source_install, "bundle_id": a.manifest.bundle_id, "crate_sha256": a.crate_sha256,
                    "phase": PHASE_ROWS_COMMITTED, "key_map": ctx.idmap.as_json(), "side": str(a.side.path) if a.side else None,
                    "created": {**{k: v for k, v in ctx.created.items()}, "project": {k: project[k] for k in ("project_id", "created")}}})
                ledger.write_undo(conn, import_id, row_journal.record_of({MAIN_STORE: row_journal.finish(conn, tracked)}))
        return ctx, project, changed
    finally:
        conn.close()


def _restored_group_name(a: an.Analysis) -> str:
    return f"restored from {a.manifest.label or a.manifest.bundle_id} {str(a.manifest.created_at or '')[:10]}".strip()


def _notify(project: Dict[str, Any], post: Dict[str, Any]) -> None:
    topics = [resource_topics.PROJECTS, f"cplug.huddle.list:{project['project_id']}", "cplug.huddle.list:all"]
    side = post.get("side") or {}
    if (side.get(rows_side.AUTOMATION_TABLES[0]) or {}).get("inserted"):
        topics.append(resource_topics.AUTOMATIONS)
    if (side.get(rows_side.BOOKMARK_TABLE) or {}).get("inserted"):
        topics.append(resource_topics.BOOKMARKS)
    for topic in topics:
        try:
            resource_push.notify(topic)
        except (RuntimeError, ValueError) as exc:
            logger.warning("crate_import_notify_failed", topic=topic, error=str(exc))


def _post_writes(reader: CrateReader, env: ImportEnv, a: an.Analysis, import_id: str,
                 key_map: Optional[Dict[str, Any]] = None, log: Optional[Callable[[Dict[str, Any]], None]] = None,
                 undo_out: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    conn = env.connect()
    side_journal: Dict[str, Any] = {}
    try:
        entry = ledger.read_entry(conn, import_id) or {}
        idmap = IdMap(key_map if key_map is not None else (entry.get("key_map") or {}))
        side = rows_side.write_side(Path(env.state), conn, idmap, a.rows.sanitized if a.rows else {}, a.col, new_root=str(a.decision.root_to),
                                    journal=side_journal)
        plugins = (plugin_data_in.place_plugin_data(reader, env, idmap, import_id, a.col, conn, log)
                   if an.restores_plugin_data(a.request, a.prov) else None)
    finally:
        conn.close()
    kept = project_files_place.keep_git_state(reader, a.side, env, import_id) if a.side is not None else None
    tasks = task_files_in.place_task_files(reader, Path(env.state), idmap, a.col, log)
    entry_undo: List[Dict[str, Any]] = []
    entries = entries_in.apply_entries(reader, env.config_path, idmap, a.decision.mapping, own=a.prov.own, col=a.col,
                                       theme_installed=env.theme_installed, undo=entry_undo)
    if undo_out is not None:
        undo_out.update(side=side_journal, entries=entry_undo)
    folder_backups = backups_folder_apply.apply(reader, a, env, log)
    return {"side": {k: v.as_json() for k, v in sorted(side.items())}, "task_files": tasks.as_json(), "entries": entries,
            "plugin_data": plugins.as_json() if plugins is not None else {}, "project_git_kept": kept, "folder_backups": folder_backups}


def _journal_step(env: ImportEnv, a: an.Analysis, import_id: str) -> journal_in.JournalOutcome:
    conn = env.connect()
    try:
        entry = ledger.read_entry(conn, import_id) or {}
    finally:
        conn.close()
    done = entry.get("journal")
    if isinstance(done, dict) and done.get("state"):
        return journal_in.JournalOutcome(str(done["state"]), int(done.get("rewritten") or 0))
    outcome = journal_in.rebase_for_import(Path(env.state), a.decision.mapping, imported_uuids(a))
    if outcome.state == journal_in.JOURNAL_UPDATED:
        row_journal.merge_fields(Path(env.state), import_id, journal={"rules": [list(r) for r in a.decision.mapping.rules], "uuids": imported_uuids(a)})
    if outcome.state in (journal_in.JOURNAL_UPDATED, journal_in.JOURNAL_NOTHING, journal_in.JOURNAL_NOT_NEEDED):
        wconn = connect(db_path_for(Path(env.state)), create=False)
        try:
            with transaction(wconn):
                ledger.set_field(wconn, import_id, "journal", outcome.as_json())
        finally:
            wconn.close()
    return outcome


def _post_changed(post: Dict[str, Any]) -> bool:
    plugin = post.get("plugin_data") or {}
    return bool((post.get("folder_backups") or {}).get("adopted") or any((c or {}).get("inserted") for c in post["side"].values()) or (post["task_files"] or {}).get("written")
                or plugin.get("written") or any(b.get("relinked") for b in plugin.get("boards") or [])
                or any((post["entries"] or {}).get(k) for k in ("drawer_members", "pins", "themes")))


def _record_undo(env: ImportEnv, import_id: str, undo_out: Dict[str, Any], resumed: bool) -> None:
    state = Path(env.state)
    if resumed:
        row_journal.mark_incomplete(state, import_id)
        return
    for store, tables in (undo_out.get("side") or {}).items():
        row_journal.merge_store(state, import_id, store, tables)
    if undo_out.get("entries"):
        row_journal.merge_fields(state, import_id, entries=undo_out["entries"])


def _after(reader: CrateReader, env: ImportEnv, a: an.Analysis, counts: Dict[str, rows_write.TableCounts], created: Dict[str, List[Any]],
           placed: files_apply.PlacedFiles, import_id: str, project: Dict[str, Any], changed: bool, hooks: hk.ApplyHooks,
           key_map: Optional[Dict[str, Any]] = None, resumed: bool = False) -> ImportReceipt:
    hooks.phase(hk.PHASE_POST)
    undo_out: Dict[str, Any] = {}
    post = _post_writes(reader, env, a, import_id, key_map, lambda entry: files_apply.record_undo(hooks, placed, entry), undo_out)
    _record_undo(env, import_id, undo_out, resumed)
    wrote = changed or _post_changed(post)
    _notify(project, post)
    journal = _journal_step(env, a, import_id) if changed else journal_in.JournalOutcome(journal_in.JOURNAL_NOT_NEEDED)
    if changed:
        row_journal.seal(Path(env.state), import_id)
    hooks.phase(hk.PHASE_CHECKING)
    conn = env.connect()
    try:
        checks = verify_after.run(a, env, conn, placed.written, created.get(rows_identity.SESSIONS, []))
    finally:
        conn.close()
    warnings = [w.as_json() for w in a.col.warnings] + checks.warnings()
    if journal.state in (journal_in.JOURNAL_UNREADABLE, journal_in.JOURNAL_FAILED):
        warnings.append({"code": W_JOURNAL_NOT_REBASED, "detail": journal.state})
    state = STATE_NOOP if not wrote else (STATE_DONE_WARNINGS if warnings else STATE_DONE)
    if changed:
        wconn = connect(db_path_for(Path(env.state)), create=False)
        try:
            with transaction(wconn):
                ledger.set_phase(wconn, import_id, PHASE_DONE_WARNINGS if warnings else PHASE_DONE)
        finally:
            wconn.close()
    return ImportReceipt(
        import_id=import_id, state=state, bundle_id=a.manifest.bundle_id, crate_sha256=a.crate_sha256, provenance=a.prov.kind,
        project={"id": project["project_id"], "name": a.decision.name, "root": a.decision.root_to, "action": a.decision.action},
        files={"written": len(placed.written), "same": len(placed.same), "bytes": placed.bytes},
        rows={**{k: v.as_json() for k, v in sorted(counts.items())}, **post["side"]},
        sessions=restored_sessions(a),
        conversations=a.conversations, warnings=warnings,
        not_restored=(a.rows.not_restored if a.rows else []) + plan_mod.files_not_restored(a.placements) + list((post["entries"] or {}).get("not_restored") or []),
        checks={"resume_measured": len(checks.resume_measured), "resume_unverified": dict(checks.resume_unverified),
                "file_mismatch": list(checks.file_mismatch)},
        journal=journal.as_json(), task_files=post["task_files"], entries={k: v for k, v in post["entries"].items() if k != "not_restored"},
        plugin_data=post["plugin_data"], project_files=project_files_place.receipt_block(a.side, post["project_git_kept"], placed), cleanup=dict(placed.cleanup),
        backups={**placed.backups, **({"folders": post["folder_backups"]} if post.get("folder_backups") else {})})


def apply_import(reader: CrateReader, env: ImportEnv, request: ImportRequest, *, crate_sha256: str, fingerprint: str, import_id: str,
                 hooks: Optional[hk.ApplyHooks] = None, now: Optional[str] = None) -> ImportReceipt:
    hooks = hooks or hk.ApplyHooks()
    hooks.phase(hk.PHASE_PLANNING)
    try:
        with one_move_at_a_time():
            return _locked(reader, env, request, crate_sha256, fingerprint, import_id, hooks, now)
    except MoveBusy as exc:
        raise ImportRefused("busy", str(exc)) from exc


def _locked(reader: CrateReader, env: ImportEnv, request: ImportRequest, crate_sha256: str, fingerprint: str, import_id: str,
            hooks: hk.ApplyHooks, now: Optional[str]) -> ImportReceipt:
    conn = env.connect()
    try:
        a = an.analyze(reader, env, conn, request, crate_sha256)
        fresh = plan_mod.render(a, conn)
    finally:
        conn.close()
    if fresh.get("fingerprint") != fingerprint:
        raise ImportRefused("plan_changed", "the plan changed since it was shown", plan=fresh)
    if not a.ok:
        raise ImportRefused("blocked", "the plan is blocked", plan=fresh)
    hooks.checkpoint(hk.CP_BEFORE_FILES)
    placed = files_apply.PlacedFiles()
    try:
        _measure_again(env, a)
        placed = files_apply.place_files(reader, a, env, hooks, import_id)
        root = a.decision.root_to
        if root and not (a.side is not None and not a.side.into_root and a.side.path == Path(root)):
            project_files_place.ensure_root(Path(root), hooks, placed)
        if a.side is not None:
            project_files_place.place_side(reader, a.side, hooks, placed)
        if request.keep_conversations and a.cleanup.get("needs_guard"):
            placed.cleanup = cleanup_apply.apply(env.claude_homes[0], hooks, placed)
        placed.backups = backups_apply.apply(reader, a, env, hooks, placed)
        hooks.checkpoint(hk.CP_AFTER_FILES)
        hooks.check()
        a.live = _measure_again(env, a)
        hooks.checkpoint(hk.CP_BEFORE_COMMIT)
        ctx, project, changed = _commit_rows(env, a, import_id, placed, hooks, now)
    except Exception as exc:
        report = undo.rollback(placed.log, [*files_apply.undo_roots(env), *plugin_data_in.undo_roots(placed.log, env, import_id)])
        logger.warning("crate_import_rolled_back", import_id=import_id, error_type=type(exc).__name__, removed=len(report.removed),
                       kept=len(report.kept), errors=len(report.errors))
        if isinstance(exc, ImportFailed):
            raise ImportFailed(exc.code, exc.detail + _leftovers(report), rolled_back=not report.kept and not report.errors) from exc
        if isinstance(exc, (sqlite3.Error, OSError)):
            raise ImportFailed(E_DB if isinstance(exc, sqlite3.Error) else files_apply.E_IO, f"{type(exc).__name__}: {exc}"[:300] + _leftovers(report),
                               rolled_back=not report.kept and not report.errors) from exc
        raise
    hooks.checkpoint(hk.CP_AFTER_ROWS)
    try:
        receipt = _after(reader, env, a, ctx.counts, ctx.created, placed, import_id, project, changed, hooks,
                         key_map=None if changed else ctx.idmap.as_json())
    except (sqlite3.Error, OSError) as exc:
        raise ImportFailed("post_failed", f"{type(exc).__name__}: {exc}"[:300], rolled_back=False) from exc
    hooks.checkpoint(hk.CP_AFTER_POST)
    return receipt


def _leftovers(report: undo.UndoReport) -> str:
    if not report.kept and not report.errors:
        return ""
    return f" (not removed: {', '.join((report.kept + report.errors)[:5])})"


def recover_files(entries: List[Dict[str, Any]], env: ImportEnv, import_id: Optional[str] = None) -> undo.UndoReport:
    return undo.rollback(entries, [*files_apply.undo_roots(env), *plugin_data_in.undo_roots(entries, env, import_id)])


def finish_import(reader: CrateReader, env: ImportEnv, request: ImportRequest, *, crate_sha256: str, import_id: str,
                  hooks: Optional[hk.ApplyHooks] = None) -> ImportReceipt:
    hooks = hooks or hk.ApplyHooks()
    try:
        with one_move_at_a_time():
            conn = env.connect()
            try:
                entry = ledger.read_entry(conn, import_id)
                if entry is None:
                    raise ImportRefused("no_such_import", f"no committed import {import_id}")
                a = an.analyze(reader, env, conn, request, crate_sha256, side_path=entry.get("side"))
                fresh = plan_mod.render(a, conn)
            finally:
                conn.close()
            if a.rows is None or a.decision.action is None:
                raise ImportRefused("blocked", "the crate can no longer be planned", plan=fresh)
            created = {k: v for k, v in (entry.get("created") or {}).items() if isinstance(v, list)}
            placed = files_apply.PlacedFiles(same=[str(p.dest) for p in a.placements if p.cls == files_place.CLASS_SAME and p.dest is not None])
            placed.written = list(placed.same)
            project = {"project_id": ((entry.get("created") or {}).get("project") or {}).get("project_id"), "created": False}
            return _after(reader, env, a, {}, created, placed, import_id, project, True, hooks, resumed=True)
    except MoveBusy as exc:
        raise ImportRefused("busy", str(exc)) from exc

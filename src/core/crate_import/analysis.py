
from __future__ import annotations

import copy
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.core import session_journal_store as journal_store
from src.core.crate_format.constants import LINE_ROLES
from src.core.crate_format.model import ConversationRecord, CrateManifest
from src.core.crate_format.reader import CrateReader
from src.core.crate_import import enc as enc_mod
from src.core.crate_import import entries_in, pin_homes, plugin_data_in, project_files_in, task_files_in
from src.core.crate_import import backups_folder_in, backups_in, cleanup_guard, files_place, guard, rows_plan, session_plan, share_in, target
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.model import (
    B_BAD_IDENTIFIER, B_BAD_REQUEST, B_CLEANUP_SETTINGS, B_CONFLICT, B_NO_SPACE, B_OWNED_ELSEWHERE, CLASS_CONFLICT, CLASS_EXCLUDED, CLASS_GROW, CLASS_LIVE, CLASS_LOCAL_NEWER, CLASS_NOT_RESTORED,
    CLASS_PRESENT, CLASS_WRITE, FOREIGN, RESUME_FILE_ONLY, RESUME_FORK, RESUME_NATIVE, W_CLAIMS_THIS_COMPUTER, W_CLOUD_ONLY,
    Collector, ImportRequest,
)
from src.core.crate_import.journal_in import mapping_moves
from src.core.crate_import.provenance import Provenance, provenance_of
from src.core.pack.migrate.receive import DISK_HEADROOM
from src.core.project_move.paths import rebase_journal_for

_RESUME_LABEL = {"claude_resume": RESUME_NATIVE, "fork_only": RESUME_FORK}


@dataclass
class Analysis:

    manifest: CrateManifest
    request: ImportRequest
    crate_sha256: str
    prov: Provenance
    source_install: Optional[str]
    crate_project: target.CrateProject
    crate_sessions: List[Tuple[str, Optional[str]]]
    live: guard.LiveFacts
    decision: target.TargetDecision
    col: Collector
    rows: Optional[rows_plan.RowsPlan] = None
    enc: Dict[str, enc_mod.EncEntry] = field(default_factory=dict)
    placements: List[files_place.Placement] = field(default_factory=list)
    conversations: List[Dict[str, Any]] = field(default_factory=list)
    needed: int = 0
    free: int = 0
    by_home: Dict[str, int] = field(default_factory=dict)
    journal_rebased: int = 0
    entries: Dict[str, int] = field(default_factory=dict)
    task_files: int = 0
    plugin_data: List[Dict[str, Any]] = field(default_factory=list)
    side: Optional[project_files_in.SidePlan] = None
    carries: Dict[str, bool] = field(default_factory=dict)
    cleanup: Dict[str, Any] = field(default_factory=dict)
    backup_points: Dict[str, List[Any]] = field(default_factory=dict)
    backups: Dict[str, Any] = field(default_factory=dict)
    folder_points: Dict[str, List[Any]] = field(default_factory=dict)
    homes: Dict[str, Path] = field(default_factory=dict)
    volume: str = ""
    sessions: session_plan.SessionPlan = field(default_factory=session_plan.SessionPlan)

    @property
    def ok(self) -> bool:
        return not self.col.blockers and self.decision.action is not None


def crate_project_of(manifest: CrateManifest, project_raw_path: Optional[str]) -> target.CrateProject:
    scope = manifest.scope or {}
    dirs = tuple(dict.fromkeys(c.working_dir for c in manifest.conversations if c.working_dir))
    return target.CrateProject(
        scope=str(scope.get("kind") or "project"), uid=scope.get("project_uid"), root=scope.get("project_root"),
        raw_path=project_raw_path, name=scope.get("project_name") or scope.get("title"), created_epoch=manifest.created_epoch,
        working_dirs=dirs)


def crate_homes(manifest: CrateManifest) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    for home in manifest.homes:
        out.setdefault(home.kind, home.path)
    return out


def resume_label(record: ConversationRecord) -> str:
    if record.family == "codex":
        return RESUME_FILE_ONLY
    return _RESUME_LABEL.get(record.resume, RESUME_FILE_ONLY)


def not_restored_reason(conversation_id: str, placements: List[files_place.Placement]) -> str:
    reasons = [p.reason for p in placements if p.record.conversation_id == conversation_id and p.cls is None]
    return reasons[0] if reasons else "copy_role"


def conversation_class(record: ConversationRecord, placements: List[files_place.Placement], request: ImportRequest,
                       live: guard.LiveFacts, col: Collector, owned_elsewhere: bool) -> str:
    if record.id in request.exclude_conversations:
        return CLASS_EXCLUDED
    if record.id in live.live_conversations:
        return CLASS_LIVE
    all_mine = [p for p in placements if p.record.conversation_id == record.id]
    mine = [p for p in all_mine if p.cls is not None]
    if all_mine and not mine:
        return CLASS_NOT_RESTORED
    classes = {p.cls for p in mine}
    gating = {p.cls for p in mine if p.record.role in LINE_ROLES or p.cls == files_place.CLASS_UNSAFE}
    if files_place.CLASS_CLOUD_ONLY in classes:
        col.warn(W_CLOUD_ONLY, record.id)
    bad = {files_place.CLASS_CONFLICT, files_place.CLASS_CLOUD_ONLY, files_place.CLASS_UNSAFE}
    if gating & bad:
        if request.skip_conflicts:
            return CLASS_EXCLUDED
        col.block(B_OWNED_ELSEWHERE if owned_elsewhere else B_CONFLICT, record.id)
        return CLASS_CONFLICT
    if files_place.CLASS_GROW in classes:
        return CLASS_GROW
    if files_place.CLASS_LOCAL_NEWER in classes:
        return CLASS_LOCAL_NEWER
    if classes and classes <= {files_place.CLASS_SAME}:
        return CLASS_PRESENT
    return CLASS_WRITE


def lstat_key(path: Any) -> List[Any]:
    try:
        info = os.lstat(path)
    except OSError:
        return [False, 0, 0, 0]
    return [True, info.st_ino, info.st_size, info.st_mtime_ns]


def _journal_rebased(env: ImportEnv, mapping: Any, imported: List[str]) -> int:
    if not mapping_moves(mapping) or not imported:
        return 0
    loaded = journal_store.load_journal(env.state)
    if loaded.outcome != journal_store.LOAD_OK:
        return 0
    return rebase_journal_for(copy.deepcopy(loaded.journal), mapping, imported)


def table_of(reader: CrateReader, name: str) -> Optional[Tuple[str, str]]:
    for store, by_name in reader.tables().items():
        if name in by_name and by_name[name].inventory_label == "cloude.db":
            return store, name
    return None


def restores_plugin_data(request: ImportRequest, prov: Provenance) -> bool:
    return bool(request.include_plugin_data or prov.own)


def work_in_copy(decision: target.TargetDecision, crate: target.CrateProject, request: ImportRequest, env: ImportEnv,
                 homes: Dict[str, Optional[str]], side: Path, *, rerun: bool, col: Collector) -> bool:
    if decision.action == target.ACTION_CREATE and not rerun:
        decision.root_to, decision.adoptions = str(side), []
    elif not rerun:
        col.block(B_BAD_REQUEST, "work_in_restored_copy needs a project that is not here yet; this one is already here")
        return False
    target.rebase_mapping(decision, crate, request, env, homes, str(decision.root_to))
    return True


def analyze(reader: CrateReader, env: ImportEnv, conn: Any, request: ImportRequest, crate_sha256: str,
            side_path: Optional[str] = None) -> Analysis:
    manifest, col = reader.manifest, Collector()
    prov = provenance_of(conn, manifest.source, manifest.bundle_id, crate_sha256, env.install_id, made_here=request.made_here,
                         share=share_in.is_share(manifest))
    if prov.kind == FOREIGN and prov.claims_this_install:
        col.warn(W_CLAIMS_THIS_COMPUTER, manifest.bundle_id)
    source_install = manifest.source.get("install_id")
    sessions_at, projects_at = table_of(reader, "sessions"), table_of(reader, "projects")
    raw_sessions = list(reader.rows(*sessions_at)) if sessions_at else []
    crate_sessions = [(str(r.get("session_uuid")), r.get("claude_session_uuid")) for r in raw_sessions if r.get("session_uuid")]
    projects = list(reader.rows(*projects_at)) if projects_at else []
    crate_project = crate_project_of(manifest, projects[0].get("raw_path") if projects else None)
    first_dir = crate_project.working_dirs[0] if crate_project.working_dirs else crate_project.root
    live = guard.measure(env, conn, crate_sessions, [c.id for c in manifest.conversations], request.new_root or first_dir, col)
    decision = target.decide(crate_project, request, prov, env, conn, col, live_row_ids=live.live_row_ids,
                             crate_homes=crate_homes(manifest))
    out = Analysis(manifest, request, crate_sha256, prov, source_install, crate_project, crate_sessions, live, decision, col)
    files = reader.files()
    has_files = bool(project_files_in.project_records(files))
    out.carries = {"project_files": has_files, "work_in_restored_copy": has_files and prov.own and decision.action in (None, target.ACTION_CREATE),
                   "plugin_data": bool(plugin_data_in.stores_of(reader))}
    if decision.action is None:
        return out
    homes = crate_homes(manifest)
    out.side = project_files_in.plan_side(reader, files, crate_project, decision, request, prov, env, col, side_path)
    if out.side is not None and out.side.work_here and not work_in_copy(decision, crate_project, request, env, homes, out.side.path,
                                                                        rerun=side_path is not None, col=col):
        return out
    out.homes = pin_homes.conversation_homes(reader, manifest, env, own=prov.own)
    if share_in.is_share(manifest) and share_in.bad_identifiers(manifest):
        col.block(B_BAD_IDENTIFIER, f"conversation id: {share_in.bad_identifiers(manifest)[0][:40]!r} is not a uuid")
        return out
    out.enc = (share_in.enc_for(decision.root_to) if share_in.is_share(manifest) and decision.root_to
               else enc_mod.plan_enc(reader, manifest.conversations, files, decision.mapping, request.mode, col))
    out.placements = files_place.plan_files(reader, files, env, out.enc, own=prov.own, include_instructions=request.include_instructions,
                                            excluded_conversations=frozenset(request.exclude_conversations),
                                            include_project_files=request.include_project_files, conversation_homes=out.homes)
    elsewhere = session_plan.held_by(conn, crate_sessions)
    by_session = {u: c for u, c in crate_sessions}
    for record in manifest.conversations:
        held = bool(elsewhere.get(record.id)) or (record.session_uuid is not None and bool(elsewhere.get(by_session.get(record.session_uuid) or "")))
        cls = conversation_class(record, out.placements, request, live, col, held)
        row = {"id": record.id, "title": record.title, "class": cls, "resume": resume_label(record)}
        if cls == CLASS_NOT_RESTORED:
            row["reason"] = not_restored_reason(record.id, out.placements)
        out.conversations.append(row)
    writing = (files_place.CLASS_ABSENT, files_place.CLASS_GROW)
    excluded = frozenset(c["id"] for c in out.conversations if c["class"] == CLASS_EXCLUDED)
    out.sessions = session_plan.plan_sessions(conn, raw_sessions, excluded, manifest.bundle_id, col)
    out.rows = rows_plan.plan_rows(reader, env, conn, decision.mapping, prov, source_install, col, sessions=out.sessions)
    out.needed = sum(p.record.length for p in out.placements if p.action == files_place.ACT_PLACE and p.cls in writing)
    out.free = env.free_bytes(env.claude_projects_root())
    out.volume = str(env.claude_projects_root())
    if out.needed * DISK_HEADROOM > out.free:
        col.block(B_NO_SPACE, f"needs {out.needed} bytes, {out.free} free")
    for p in out.placements:
        if p.action == files_place.ACT_PLACE and p.cls in writing:
            out.by_home[p.record.home] = out.by_home.get(p.record.home, 0) + 1
    out.cleanup = cleanup_guard.plan(out.placements, frozenset(c["id"] for c in out.conversations if c["class"] in (CLASS_WRITE, CLASS_GROW)),
                                     env.claude_homes[0])
    if request.keep_conversations and out.cleanup["needs_guard"] and out.cleanup["refused"]:
        col.block(B_CLEANUP_SETTINGS, "claude's settings.json cannot be read as JSON")
    out.backup_points = backups_in.carried(reader, files)
    out.backups = backups_in.plan_view(out.backup_points, env, filing=prov.own or request.file_backups, excluded=sorted(excluded | frozenset(request.exclude_conversations)))
    out.folder_points = backups_folder_in.carried(reader, files)
    stores = {s.key: s for s in plugin_data_in.stores_of(reader)} if out.folder_points else {}
    chosen = (lambda unit: True) if prov.own else (lambda unit: unit in request.file_backup_units)
    backups_folder_in.merge_view(out.backups, backups_folder_in.plan_rows(
        out.folder_points, backups_folder_in.FolderCtx(env, chosen, restores_plugin_data(request, prov), stores), backups_in.adopter(env)))
    out.entries = entries_in.summarize(reader)
    out.task_files = len(task_files_in.carried(files))
    out.plugin_data = plugin_data_in.preview(plugin_data_in.stores_of(reader), env, restores_plugin_data(request, prov))
    out.journal_rebased = _journal_rebased(env, decision.mapping, [u for u, _c in crate_sessions])
    return out

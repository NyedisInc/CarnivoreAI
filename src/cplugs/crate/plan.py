
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from src.cplugs.crate import constants as K
from src.cplugs.crate import folders
from src.cplugs.crate import policy as P
from src.cplugs.crate.entries_out import ScopeKeys, read_entries
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.forbidden import allowed_roots, deny_inodes, project_root_problem
from src.cplugs.crate.plan_files import FilePlanner, PlannedFile, conversation_records
from src.cplugs.crate.plugin_files import plan_plugin_store, store_view
from src.cplugs.crate.project_files import ARTIFACT as PROJECT_ARTIFACT
from src.cplugs.crate.project_files import walk_project
from src.cplugs.crate.backup_points import plan_backups
from src.cplugs.crate.folder_backups import plan_folder_backups
from src.cplugs.crate.vault_files import VaultWalk, plan_vault
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs

_LINES_SOURCE = {"claude": "claude-history", "codex": "codex-session-index"}
_SPLIT = re.compile(r"[\s,]+")


class RecipientInvalid(ValueError):
    pass


@dataclass(frozen=True)
class ExportRequest:

    scope: str
    target: str
    variant: str
    encrypt: bool = False
    recipients: Tuple[str, ...] = ()
    label: Optional[str] = None
    include_project_files: bool = False
    include_backups: bool = False
    backup_units: Tuple[str, ...] = ()

    def as_json(self) -> Dict[str, Any]:
        out = {"scope": self.scope, "target": self.target, "variant": self.variant, "encrypt": self.encrypt,
               "recipients": list(self.recipients), "label": self.label}
        if self.include_project_files:
            out["include_project_files"] = True
        if self.include_backups:
            out["include_backups"] = True
        if self.backup_units:
            out["backup_units"] = sorted(self.backup_units)
        return out


@dataclass
class ExportPlan:

    request: ExportRequest
    subject: Dict[str, Any] = field(default_factory=dict)
    home_project: Dict[str, Any] = field(default_factory=dict)
    files: List[PlannedFile] = field(default_factory=list)
    row_queries: List[cs.RowQuery] = field(default_factory=list)
    secret_columns: Dict[Tuple[str, str], List[str]] = field(default_factory=dict)
    row_fields: Dict[Tuple[str, str], Dict[str, List[str]]] = field(default_factory=dict)
    row_counts: Dict[Tuple[str, str], int] = field(default_factory=dict)
    entries: List[cs.Artifact] = field(default_factory=list)
    lines: List[Dict[str, Any]] = field(default_factory=list)
    excluded: List[Dict[str, Any]] = field(default_factory=list)
    reconcile: List[Dict[str, Any]] = field(default_factory=list)
    blockers: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    conversations: List[Dict[str, Any]] = field(default_factory=list)
    keys: ScopeKeys = field(default_factory=ScopeKeys)
    homes: Optional[P.HomesView] = None
    roots: List[str] = field(default_factory=list)
    folder: Optional[str] = None
    project: Optional[Dict[str, Any]] = None
    project_root: Optional[str] = None
    backup_families: List[Dict[str, Any]] = field(default_factory=list)
    plugin_stores: List[Dict[str, Any]] = field(default_factory=list)
    recipients: List[str] = field(default_factory=list)
    material: List[List[str]] = field(default_factory=list)
    estimate_bytes: int = 0
    fingerprint: str = ""

    @property
    def v1_1(self) -> bool:
        return self.request.include_project_files or any(f.plugin for f in self.files)

    @property
    def ok(self) -> bool:
        return not self.blockers

    def block(self, code: str, detail: str) -> None:
        self.blockers.append({"code": code, "detail": detail})


def split_recipients(text: str) -> Tuple[str, ...]:
    return tuple(p for p in _SPLIT.split(text or "") if p)


def _check_recipients(plan: ExportPlan) -> None:
    if not plan.request.encrypt:
        return
    for text in plan.request.recipients:
        try:
            cf.parse_recipient(text)
        except cf.KeyFormatError as exc:
            raise RecipientInvalid(f"{text[:12]}... is not an age public key") from exc
    plan.recipients = list(plan.request.recipients)
    if not plan.recipients:
        plan.block(K.B_RECIPIENTS, "encryption is on and no age public key was given or set")


def _sessions(inv: cs.Inventory) -> List[cs.SessionIdentity]:
    if inv.session is not None:
        return [inv.session]
    return [c.session for c in inv.children if c.session is not None]


def _scope_ids(inv: cs.Inventory) -> Dict[str, Optional[cs.SessionIdentity]]:
    out: Dict[str, Optional[cs.SessionIdentity]] = {}
    for scope in ([inv] if inv.session is not None else inv.children):
        for conv in scope.conversations:
            if K.CONVERSATION_ID_RE.match(conv):
                out.setdefault(conv, scope.session)
    return out


def _keys(inv: cs.Inventory, sessions: Sequence[cs.SessionIdentity]) -> ScopeKeys:
    keys = ScopeKeys({s.session_uuid for s in sessions}, {s.row_id for s in sessions})
    if inv.project is not None:
        keys.project_ids.add(inv.project.project_id)
        if inv.project.company_id is not None:
            keys.company_ids.add(inv.project.company_id)
    return keys


def _liveness(plan: ExportPlan, env: CrateEnv, sessions: Sequence[cs.SessionIdentity]) -> None:
    listing = env.live_panes()
    for ident in sessions:
        if not cs.is_local_host(ident.host_key):
            plan.block(K.B_REMOTE, f"{ident.display_name} runs on another computer ({ident.host_key})")
        reason = cs.live_blocker(ident, listing)
        if reason:
            plan.block(K.B_LIVE, f"{ident.display_name}: {reason}")


def _add_rows(plan: ExportPlan, art: cs.Artifact) -> None:
    loc = art.locator
    if art.count == 0 and "could not be read" in art.reason:
        plan.block(K.B_ROWS, f"{art.store} table {art.table} {art.reason}")
        return
    if not loc.get("where"):
        plan.block(K.B_NO_POLICY, f"{art.store} table {art.table} has no locator to read it by")
        return
    plan.row_queries.append(cs.RowQuery(loc.get("db"), art.store, str(loc["table"]), str(loc["where"]),
                                        tuple(loc.get("params") or ())))
    key = (art.store, str(loc["table"]))
    fields = plan.row_fields.setdefault(key, {"keys": [], "paths": []})
    for ref in art.rewrite:
        bucket = {cs.ROLE_KEY: fields["keys"], cs.ROLE_PATH: fields["paths"]}.get(ref.role)
        if ref.role == cs.ROLE_SECRET:
            plan.secret_columns.setdefault(key, [])
            if ref.name not in plan.secret_columns[key]:
                plan.secret_columns[key].append(ref.name)
        elif bucket is not None and ref.name not in bucket:
            bucket.append(ref.name)
    plan.row_counts.setdefault(key, 0)


def _reconcile_row(art: cs.Artifact, decision: P.Decision, share: bool) -> Dict[str, Any]:
    row = {"store": art.store, "kind": art.kind, "inventory_count": art.count, "inventory_size": art.size,
           "decision": decision.action, "reason": decision.reason}
    left = int(art.locator.get("out_of_scope") or 0)
    if left:
        row["out_of_scope"] = left
        row["reason"] = f"{decision.reason} ({left} left out: they belong to other tasks or projects than this export)"
    if not share:
        row["what"] = art.what
    return row


def _sort_artifacts(plan: ExportPlan, inv: cs.Inventory, planner: FilePlanner) -> None:
    share = plan.request.variant == P.SHARE
    seen = set()
    for art in inv.all_artifacts():
        ident = (art.store, art.kind, art.what, repr(sorted(art.locator.items(), key=lambda kv: kv[0])))
        if ident in seen:
            continue
        seen.add(ident)
        decision = P.decide(art, plan.request.variant, planner.homes, plan.request.include_backups)
        plan.material.append([str(x) for x in art.material()] + [decision.action])
        plan.reconcile.append(_reconcile_row(art, decision, share))
        if art.locator.get("plugin"):
            _plugin_store(plan, planner, art, decision)
        if decision.action == P.BLOCKED:
            plan.block(K.B_NO_POLICY, f"{art.what}: {decision.reason}")
        elif decision.action in (P.EXCLUDE, P.DERIVED):
            entry = {"kind": "derived" if decision.action == P.DERIVED else "policy", "store": art.store,
                     "reason": decision.reason}
            if not share:
                entry["what"] = art.what
            plan.excluded.append(entry)
        elif art.locator.get("plugin"):
            continue
        elif art.store == cs.STORE_VAULT:
            continue
        elif art.kind == cs.KIND_ROWS:
            _add_rows(plan, art)
        elif art.kind == cs.KIND_ENTRY or art.store == cs.STORE_THEME_DOTFILE:
            plan.entries.append(art)
        elif art.kind == cs.KIND_LINES:
            placed = planner.homes.place(str(art.locator["path"]))
            plan.lines.append({"source": _LINES_SOURCE[art.store], "home_index": placed[1] if placed else 0,
                               "path": str(art.locator["path"]), "match": str(art.locator["match"])})
        else:
            planner.add(art, decision)


def _plugin_store(plan: ExportPlan, planner: FilePlanner, art: cs.Artifact, decision: P.Decision) -> None:
    walk = plan_plugin_store(art, decision, planner.deny) if decision.action == P.CARRY else None
    if walk is not None:
        planner.walk.files += walk.files
        planner.walk.blockers += walk.blockers
        planner.walk.excluded += walk.excluded
    plan.plugin_stores.append(store_view(art, decision, walk))


def _plan_project(plan: ExportPlan, env: CrateEnv, inv: cs.Inventory, deny: Set[Tuple[int, int]]) -> List[PlannedFile]:
    root = inv.project.root if plan.request.scope == cs.SCOPE_PROJECT and inv.project is not None else (
        inv.session.working_dir if inv.session is not None else None)
    if not root:
        plan.block(K.B_PROJECT_ROOT, "this has no project folder to carry")
        return []
    problem = project_root_problem(root, env.locations)
    if problem:
        plan.block(K.B_PROJECT_ROOT, problem)
        return []
    walk = walk_project(root, deny, {os.path.realpath(str(a.locator["path"])): a.store for a in inv.all_artifacts()
                                     if a.locator.get("plugin") and a.locator.get("data") and a.locator.get("path")})
    plan.project, plan.project_root = walk.view(), walk.root
    plan.excluded += walk.excluded()
    for code, detail in walk.blockers:
        plan.block(code, detail)
    plan.reconcile.append({"store": PROJECT_ARTIFACT, "kind": cs.KIND_DIR, "what": PROJECT_ARTIFACT,
                           "inventory_count": len(walk.files), "inventory_size": walk.file_bytes, "decision": P.CARRY,
                           "reason": "the project folder's files, links recorded and never followed"})
    return walk.files


def _gaps(plan: ExportPlan, declared: Sequence[str]) -> None:
    share = plan.request.variant == P.SHARE
    for store in cs.EXCLUDED_STORES:
        if store.kind != cs.GAP or cs.superseded_by_declaration(store.store, declared):
            continue
        entry = {"kind": "gap", "store": store.store, "reason": store.reason}
        if not share:
            entry["what"] = store.store
        plan.excluded.append(entry)
        plan.reconcile.append({"store": store.store, "kind": "gap", "inventory_count": 0, "inventory_size": 0,
                               "decision": "gap", "reason": store.reason})
        plan.warnings.append(f"{K.W_GAP}: {store.store} is not located per session or project, so it is not carried")


def _project_blocks(plan: ExportPlan, env: CrateEnv, inv: cs.Inventory, sessions: Sequence[cs.SessionIdentity],
                    related: Sequence[str]) -> None:
    for sentence in list(inv.blockers) + [b for c in inv.children for b in c.blockers]:
        plan.block(K.B_INVENTORY, sentence)
    for sentence in related:
        plan.block(K.B_NOT_TRACED, sentence)
    problems, counts = cs.preflight(plan.row_queries, state_dir=env.state)
    for sentence in problems:
        plan.block(K.B_ROWS, sentence)
    plan.row_counts.update(counts)
    plan.warnings += [f"{K.W_OUTSIDE}: {s}" for s in list(inv.outside) + [o for c in inv.children for o in c.outside]]
    try:
        relatives = cs.fork_relatives([s.row_id for s in sessions], state_dir=env.state)
    except cs.SourceUnavailable as exc:
        plan.block(K.B_ROWS, f"fork links could not be read ({exc})")
        relatives = []
    plan.warnings += [f"{K.W_FORK_PARENT}: session {child} is a fork of {parent}, which this export does not carry"
                      for child, parent in relatives]
    if plan.request.variant == P.SHARE:
        ids = {inv.project.project_id} if inv.project is not None else {s.project_id for s in sessions}
        for pid in sorted(ids, key=lambda p: (p is None, p or 0)):
            gapped = None if pid is None else cs.project_air_gapped(pid, state_dir=env.state)
            if gapped is None or gapped:
                plan.block(K.B_AIR_GAP, "the project is air gapped (or its flag cannot be read); a share is refused")


def _missing(plan: ExportPlan, inv: cs.Inventory, missing: Sequence[str]) -> None:
    for conv in missing:
        legacy = any(a.store == cs.STORE_POINTS and os.path.basename(a.what) == conv for a in inv.all_artifacts())
        detail = f"conversation {conv} has no transcript on disk and no backup holds it"
        if legacy:
            detail += "; a legacy restore point exists; turn the backup vault on so it migrates the point, then export again"
        plan.block(K.B_MISSING, detail)


def _space_and_folder(plan: ExportPlan, env: CrateEnv) -> None:
    plan.estimate_bytes = sum(f.size for f in plan.files) + K.ROW_ESTIMATE_BYTES * sum(plan.row_counts.values())
    try:
        folder = folders.resolve(env, K.FOLDER_PRIMARY)
        if plan.request.variant == P.SHARE:
            folder = folders.share_folder(folder)
    except folders.FolderUnavailable as exc:
        plan.block(K.B_FOLDER, exc.detail)
        return
    plan.folder = str(folder)
    need = int(plan.estimate_bytes * K.SPACE_FACTOR) + K.SPACE_RESERVE_BYTES
    free = folders.free_bytes(folder)
    if free < need:
        plan.block(K.B_SPACE, f"{folder} has {free} bytes free; this export needs about {need}")


def fingerprint_of(plan: ExportPlan) -> str:
    body = {"request": plan.request.as_json(), "artifacts": sorted(plan.material),
            "files": sorted([str(x) for x in f.material()] for f in plan.files)}
    return hashlib.sha256(cf.canonical.dumps(body)).hexdigest()


def build_plan(env: CrateEnv, request: ExportRequest) -> ExportPlan:
    if request.variant not in (P.OWN, P.SHARE):
        raise ValueError(f"unknown variant {request.variant!r}")
    if request.include_project_files and request.variant != P.OWN:
        raise ValueError("the project's files are carried by an own copy only")
    if (request.include_backups or request.backup_units) and request.variant != P.OWN:
        raise ValueError("the backup points are carried by an own copy only")
    plan = ExportPlan(request=request)
    _check_recipients(plan)
    related: List[str] = []
    inv = cs.resolve(request.scope, request.target, env.locations, related_blockers=related)
    sessions = _sessions(inv)
    plan.subject = inv.session.as_dict() if inv.session is not None else (inv.project.as_dict() if inv.project else {})
    plan.home_project = inv.home_project.as_dict() if inv.home_project is not None else {}
    plan.keys = _keys(inv, sessions)
    plan.homes = P.HomesView.of(env.locations)
    plan.roots = allowed_roots(env.locations)
    scope_ids = _scope_ids(inv)
    deny = deny_inodes(env.locations)
    planner = FilePlanner(plan.homes, plan.roots, deny, list(scope_ids))
    _liveness(plan, env, sessions)
    _sort_artifacts(plan, inv, planner)
    vault = plan_vault(list(scope_ids), planner.walk.files, planner.walk.refused, plan.homes, request.variant)
    project_files = _plan_project(plan, env, inv, deny) if request.include_project_files else []
    backups = plan_backups(list(scope_ids), cs.backup_provider_id(env.locations)) if request.include_backups else VaultWalk()
    folder_backups = (plan_folder_backups(request.backup_units, cs.backup_families(inv, env.locations), cs.backup_provider_id(env.locations))
                      if request.backup_units else None)
    if folder_backups is not None:
        backups.files += folder_backups.walk.files
        backups.blockers += folder_backups.walk.blockers
        backups.warnings += folder_backups.walk.warnings
        backups.reconcile += folder_backups.walk.reconcile
        plan.backup_families = folder_backups.carried
    vault.blockers += backups.blockers
    vault.warnings += backups.warnings
    vault.reconcile += backups.reconcile
    plan.files = sorted(planner.walk.files + vault.files + backups.files + project_files, key=lambda f: f.sort_key)
    plan.excluded += planner.walk.excluded
    plan.warnings += planner.walk.warnings + vault.warnings
    plan.reconcile += vault.reconcile
    for code, detail in planner.walk.blockers + vault.blockers:
        plan.block(code, detail)
    for f in plan.files:
        if f.role == P.R_ORPHAN and f.conversation_id:
            scope_ids.setdefault(f.conversation_id, None)
    plan.conversations, missing = conversation_records(sessions, scope_ids, plan.files)
    _missing(plan, inv, [c for c in missing if c not in planner.walk.refused and c not in vault.troubled])
    _gaps(plan, cs.declared_store_rels(env.locations))
    _records, entry_blockers = read_entries(plan.entries, plan.keys, env.locations)
    for sentence in entry_blockers:
        plan.block(K.B_ENTRY, sentence)
    _project_blocks(plan, env, inv, sessions, related)
    _space_and_folder(plan, env)
    plan.fingerprint = fingerprint_of(plan)
    return plan

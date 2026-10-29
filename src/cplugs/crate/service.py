
from __future__ import annotations

import asyncio
import re
import sqlite3
from typing import Any, Callable, Dict, List, Mapping, Optional

from src.cplugs.crate import constants as K
from src.cplugs.crate import folders, writer
from src.cplugs.crate import policy as P
from src.cplugs.crate.copying import CopyFailed
from src.cplugs.crate.entries_out import EntryUnreadable
from src.cplugs.crate.env import CrateEnv, from_ctx
from src.cplugs.crate.errors import CrateApiError, conflict, invalid, not_found
from src.cplugs.crate.forbidden import DatalessSource, SourceForbidden
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.jobs import runner, state
from src.cplugs.crate.plan import ExportPlan, ExportRequest, RecipientInvalid, build_plan, split_recipients
from src.cplugs.crate.refs import all_bundles
from src.cplugs.crate.share import ShareResidualSecret, ShareUnscannable
from src.cplugs.crate.source_read import SourceUnstable
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs
from src.cplugs.sdk import exports as sx

_JOB_ERRORS = ((SourceUnstable, "source_unstable"), (DatalessSource, "source_dataless"),
               (SourceForbidden, "source_forbidden"), (cs.SourceUnavailable, "source_unavailable"),
               (ShareUnscannable, "share_unscannable"), (ShareResidualSecret, "share_residual_secret"),
               (EntryUnreadable, "entry_unreadable"), (cf.CrateError, "crate_unreadable"),
               (sx.ExportsError, "record_failed"),
               (sqlite3.Error, "record_failed"), (OSError, "io_failed"))


def env_of(ctx: Any) -> CrateEnv:
    return from_ctx(ctx)


def _jsonable(detail: Any) -> Any:
    return detail if isinstance(detail, (str, int, float, list, dict)) or detail is None else str(detail)


_UNIT = re.compile(r"^[a-z][a-z0-9_-]{0,63}\.[a-z][a-z0-9_-]{0,63}$")

PLAN_CHANGED_SENTENCE = ("the plan changed since it was shown; preview again with the same label and options "
                         "as the export (the label and options are part of the fingerprint)")


def job_failure(exc: BaseException) -> runner.JobFailed:
    if isinstance(exc, writer.ExportRefused):
        detail = PLAN_CHANGED_SENTENCE if exc.code == "plan_changed" else exc.detail
        return runner.JobFailed(exc.code, _jsonable(detail))
    if isinstance(exc, (writer.ExportFailed, CopyFailed, folders.FolderUnavailable)):
        return runner.JobFailed(exc.code, _jsonable(exc.detail))
    code = next((c for cls, c in _JOB_ERRORS if isinstance(exc, cls)), K.E_JOB_CRASHED)
    return runner.JobFailed(code, f"{type(exc).__name__}: {exc}"[:600])


_KNOWN = (writer.ExportRefused, writer.ExportFailed, CopyFailed, folders.FolderUnavailable) + tuple(
    cls for cls, _code in _JOB_ERRORS)


def guarded(work: Callable[[JobHandle], Dict[str, Any]]) -> Callable[[JobHandle], Dict[str, Any]]:
    def run(handle: JobHandle) -> Dict[str, Any]:
        try:
            return work(handle)
        except _KNOWN as exc:
            raise job_failure(exc) from exc

    return run


def start_job(ctx: Any, env: CrateEnv, kind: str, request: Dict[str, Any],
              work: Callable[[JobHandle], Dict[str, Any]]) -> str:
    try:
        return runner.start(env.work, kind, request, guarded(work), notify=ctx.notify)
    except runner.JobBusy as exc:
        raise conflict(exc.code, str(exc)) from exc


def request_of(env: CrateEnv, body: Mapping[str, Any]) -> ExportRequest:
    scope, variant, target = body.get("scope"), body.get("variant", P.OWN), body.get("target")
    if scope not in (cs.SCOPE_SESSION, cs.SCOPE_PROJECT):
        raise invalid("bad_scope", "scope is session or project")
    if variant not in (P.OWN, P.SHARE):
        raise invalid("bad_variant", "variant is own or share")
    if not isinstance(target, str) or not target.strip() or len(target) > 1024:
        raise invalid("bad_target", "target is a session or project name, id or folder (1 to 1024 characters)")
    encrypt = body.get("encrypt")
    if encrypt is None:
        encrypt = bool(env.setting("encryptByDefault", False)) and variant == P.OWN
    recipients = body.get("recipients")
    if recipients is None:
        recipients = list(split_recipients(str(env.setting("recipients", "") or "")))
    if not isinstance(recipients, list) or not all(isinstance(r, str) for r in recipients):
        raise invalid("bad_recipients", "recipients is a list of age public keys")
    label = body.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > K.LABEL_MAX):
        raise invalid("bad_label", f"label is text of at most {K.LABEL_MAX} characters")
    project_files = body.get("include_project_files", False)
    if not isinstance(project_files, bool):
        raise invalid("bad_project_files", "include_project_files is true or false")
    if project_files and variant != P.OWN:
        raise invalid("project_files_share", "the project's files go into an own copy only; a share is redacted text and "
                                              "never carries them")
    backups = body.get("include_backups", False)
    if not isinstance(backups, bool):
        raise invalid("bad_backups", "include_backups is true or false")
    if backups and variant != P.OWN:
        raise invalid("backups_share", "the backup points go into an own copy only; a share carries the conversation itself")
    units = body.get("backup_units") or []
    if not isinstance(units, list) or not all(isinstance(u, str) and _UNIT.match(u) for u in units):
        raise invalid("bad_backup_units", "backup_units is a list of plugin folder units, each <plugin>.<data id>")
    if units and variant != P.OWN:
        raise invalid("backups_share", "the backup points go into an own copy only; a share carries the conversation itself")
    return ExportRequest(scope, target.strip(), variant, bool(encrypt), tuple(recipients), label or None, project_files, backups,
                         tuple(sorted(set(units))))


def plan_view(plan: ExportPlan) -> Dict[str, Any]:
    req = plan.request
    return {"ok": plan.ok, "fingerprint": plan.fingerprint, "scope": req.scope, "subject": plan.subject,
            "variant": req.variant, "encrypt": req.encrypt, "recipients": list(plan.recipients),
            "conversations": [{"id": c["id"], "family": c["family"], "title": c["title"], "origin": c.get("origin")}
                              for c in plan.conversations],
            "reconcile": [{"store": r["store"], "kind": r["kind"], "decision": r["decision"],
                           "count": r.get("inventory_count", 0), "size": r.get("inventory_size", 0),
                           "reason": r.get("reason", ""), **({"out_of_scope": r["out_of_scope"]} if r.get("out_of_scope") else {})}
                          for r in plan.reconcile],
            "excluded_count": len(plan.excluded), "blockers": list(plan.blockers), "warnings": list(plan.warnings),
            "estimate_bytes": plan.estimate_bytes, "files": len(plan.files), "folder": plan.folder,
            "project_files": plan.project, "plugin_stores": list(plan.plugin_stores),
            "backups": {"conversations": req.include_backups, "families": list(plan.backup_families)}}


def plan_now(env: CrateEnv, request: ExportRequest) -> ExportPlan:
    try:
        return build_plan(env, request)
    except cs.CrateTargetError as exc:
        if exc.code == "target_ambiguous":
            raise conflict(exc.code, {"detail": exc.detail, "candidates": exc.candidates}) from exc
        raise not_found(exc.code, exc.detail) from exc
    except RecipientInvalid as exc:
        raise invalid("bad_recipient", str(exc)) from exc
    except cs.SourceUnavailable as exc:
        raise CrateApiError(503, "source_unavailable", str(exc)) from exc


def families_now(env: CrateEnv, scope: Any, target: Any) -> Dict[str, Any]:
    if scope not in (cs.SCOPE_SESSION, cs.SCOPE_PROJECT):
        raise invalid("bad_scope", "scope is session or project")
    if not isinstance(target, str) or not target.strip() or len(target) > 1024:
        raise invalid("bad_target", "target is a session or project name, id or folder (1 to 1024 characters)")
    try:
        inv = cs.resolve(scope, target.strip(), env.locations)
    except cs.CrateTargetError as exc:
        if exc.code == "target_ambiguous":
            raise conflict(exc.code, {"detail": exc.detail, "candidates": exc.candidates}) from exc
        raise not_found(exc.code, exc.detail) from exc
    except cs.SourceUnavailable as exc:
        raise CrateApiError(503, "source_unavailable", str(exc)) from exc
    return {"conversations": {"available": cs.backup_provider_id(env.locations) is not None},
            "folders": [{k: v for k, v in f.items() if k != "root"} for f in cs.backup_families(inv, env.locations)]}


async def backup_families(ctx: Any, body: Mapping[str, Any]) -> Dict[str, Any]:
    def work() -> Dict[str, Any]:
        return families_now(env_of(ctx), body.get("scope"), body.get("target"))

    return await asyncio.to_thread(work)


async def plan(ctx: Any, body: Mapping[str, Any]) -> Dict[str, Any]:
    def work() -> Dict[str, Any]:
        env = env_of(ctx)
        return plan_view(plan_now(env, request_of(env, body)))

    return await asyncio.to_thread(work)


def _refusal(plan_: ExportPlan) -> CrateApiError:
    codes = {b["code"] for b in plan_.blockers}
    if codes == {K.B_FOLDER}:
        return conflict(K.B_FOLDER, plan_.blockers)
    if codes == {K.B_SPACE}:
        return CrateApiError(507, K.B_SPACE, plan_.blockers)
    return conflict("blocked", plan_.blockers)


async def start_export(ctx: Any, body: Mapping[str, Any], fingerprint: str) -> Dict[str, Any]:
    def work() -> Dict[str, Any]:
        env = env_of(ctx)
        fresh = plan_now(env, request_of(env, body))
        if fresh.fingerprint != fingerprint:
            raise conflict("plan_changed", plan_view(fresh))
        if not fresh.ok:
            raise _refusal(fresh)
        job_id = start_job(ctx, env, K.KIND_EXPORT, fresh.request.as_json(),
                           lambda handle: writer.run_export(env, fresh, handle).as_json())
        return {"job_id": job_id}

    return await asyncio.to_thread(work)


def _record(env: CrateEnv, job_id: str) -> state.JobRecord:
    try:
        return state.load(state.jobs_dir(env.work), job_id)
    except KeyError as exc:
        raise not_found("job_not_found", f"no job {job_id}") from exc
    except ValueError as exc:
        raise CrateApiError(500, "job_unreadable", str(exc)) from exc


async def jobs(ctx: Any, limit: int = K.JOBS_LIMIT_DEFAULT) -> Dict[str, List[Dict[str, Any]]]:
    def work() -> Dict[str, List[Dict[str, Any]]]:
        env = env_of(ctx)
        bounded = max(1, min(int(limit), K.JOBS_LIMIT_MAX))
        return {"jobs": [rec.view() for rec in state.list_jobs(state.jobs_dir(env.work), bounded)]}

    return await asyncio.to_thread(work)


async def job(ctx: Any, job_id: str) -> Dict[str, Any]:
    return await asyncio.to_thread(lambda: _record(env_of(ctx), job_id).view())


async def cancel(ctx: Any, job_id: str) -> Dict[str, bool]:
    def work() -> Dict[str, bool]:
        _record(env_of(ctx), job_id)
        return {"cancelled": runner.cancel(job_id)}

    return await asyncio.to_thread(work)


def _folder_state(env: CrateEnv, which: str) -> Optional[Dict[str, Any]]:
    if which == K.FOLDER_SECOND and not str(env.setting("secondFolder", "") or "").strip():
        return None
    try:
        path = folders.resolve(env, which)
    except folders.FolderUnavailable as exc:
        chosen = str(env.setting("folder" if which == K.FOLDER_PRIMARY else "secondFolder", "") or "")
        return {"path": chosen or None, "state": exc.state, "reason": exc.detail, "free_bytes": None}
    return {"path": str(path), "state": K.FOLDER_OK, "reason": None, "free_bytes": folders.free_bytes(path)}


async def summary(ctx: Any) -> Dict[str, Any]:
    def work() -> Dict[str, Any]:
        env = env_of(ctx)
        running = runner.running_id()
        try:
            count: Optional[int] = len(all_bundles(env))
        except (sx.MainDbUnreadable, sqlite3.Error):
            count = None
        view = _record(env, running).view() if running else None
        return {"folders": {K.FOLDER_PRIMARY: _folder_state(env, K.FOLDER_PRIMARY),
                            K.FOLDER_SECOND: _folder_state(env, K.FOLDER_SECOND)},
                "encrypt_default": bool(env.setting("encryptByDefault", False)),
                "recipients": list(split_recipients(str(env.setting("recipients", "") or ""))),
                "running_job": view, "bundles": count,
                "backups_available": cs.backup_provider_id(env.locations) is not None}

    return await asyncio.to_thread(work)

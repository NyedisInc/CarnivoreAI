
from __future__ import annotations

import asyncio
import json
import os
import shutil
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.pack.move import inflight
from src.core.pack.carry import send
from src.core.pack.identity import home
from src.core.pack.migrate import ops, transcripts
from src.core.pack.migrate.plan import ABORT, FLIP, PREPARE, RECEIVE, VERIFY, MigrateError, Plan, Request, SourceEnv, call
from src.core.pack.transport import blobs, bundles, ladder, tarball
from src.core.pack.trust_carry import imports, store as trust_store
from src.core.pack.trust_carry import wire as trust_wire

logger = structlog.get_logger()


def guarded(request: Request) -> Request:
    async def wrapped(method: str, path: str, **kw: Any):
        try:
            return await request(method, path, **kw)
        except (PeerUnreachable, PeerRefused, asyncio.TimeoutError, OSError) as exc:
            logger.info("pack_migrate_link_failed", path=path, error=type(exc).__name__)
            raise MigrateError("machine_unreachable", "the other computer is not reachable right now", 502) from exc
    return wrapped


@dataclass
class Staged:

    op_id: str
    plan: Plan
    reinstall_failed: List[str] = field(default_factory=list)


async def _db(env: SourceEnv, fn: Any) -> Any:
    def run() -> Any:
        with closing(env.open_db()) as conn:
            return fn(conn)
    return await asyncio.to_thread(run)


async def open_op(env: SourceEnv, op_id: str, *, step: str, detail: Dict[str, Any], **fields: Any) -> None:
    def run(conn: Any) -> None:
        if ops.read(conn, op_id, "source") is None:
            ops.create(conn, op_id=op_id, role="source", step=step, detail=detail, **fields)
        else:
            ops.update(conn, op_id, "source", state="applying", step=step, detail=detail)
    await _db(env, run)


async def _send(request: Request, path: str, kind: str) -> str:
    try:
        return await blobs.send_file(request, path, blob_id=blobs.new_id(), kind=kind)
    except blobs.BlobError as exc:
        raise MigrateError(exc.code, "the other computer refused a piece of the project", 502, "send") from exc


async def _carry_units(request: Request, plan: Plan, op_id: str, work: str, air_gap: bool) -> None:
    found = plan.carry
    rows = await send.send_units(request, found, project_uid=plan.project["uid"], op_id=op_id, outbox=work, air_gap=air_gap, label=plan.target_label)
    want = [r.head for r in found.repos if r.head]
    got = [row.get("head") for row in rows if "head" in row]
    if got != want:
        raise MigrateError("verify_failed", "a repo did not arrive at the commit that was sent", 409, "verify")


async def _abort_target(request: Request, op_id: str) -> None:
    try:
        await request("POST", ABORT, json={"op_id": op_id})
    except MigrateError as exc:
        logger.warning("pack_migrate_abort_unreached", op_id=op_id, code=exc.code)


async def stage_project(env: SourceEnv, plan: Plan, request: Request, *, op_id: Optional[str] = None, parent_id: Optional[str] = None) -> Staged:
    op_id, project = op_id or ops.new_id(), plan.project
    await open_op(env, op_id, kind="project", subject_uid=project["uid"], source_install_id=env.install_id,
                  target_install_id=plan.target_install_id, fingerprint=plan.fingerprint, parent_id=parent_id,
                  step="prepare", detail={"name": project["display_name"], "rung": plan.rung, "target_root": plan.target_root})
    work = os.path.join(env.outbox, op_id)
    os.makedirs(work, mode=0o700, exist_ok=True)
    air_gap = bool(project.get("air_gap"))
    step = "prepare"

    async def at(name: str) -> None:
        nonlocal step
        step = name
        await _db(env, lambda c: ops.update(c, op_id, "source", step=name))

    try:
        profiles = [env.profile_of(x["session_uuid"]) for x in plan.manifest["sessions"]]
        trusted = await asyncio.to_thread(lambda: trust_store.project_trusted(project["root"], profiles))
        imports_ok = await asyncio.to_thread(imports.source_imports_ok, project["root"], profiles)
        prep = await call(request, PREPARE, {**trust_wire.source_trusted_field(plan.target_install_id, trusted), **trust_wire.source_imports_field(plan.target_install_id, imports_ok),
            "op_id": op_id, "kind": "project", "parent_id": parent_id, "project_uid": project["uid"], "name": project["display_name"],
            "root_hint": plan.target_root, "company_uid": (plan.manifest["company"] or {}).get("uid"), "bytes_needed": plan.summary["transcript_bytes"] +
            (plan.code_meta.get("stats") or {}).get("bytes", 0)}, "prepare")
        if prep["root"] != plan.target_root or prep["case"] != plan.case:
            raise MigrateError("plan_changed", "the other computer's answer changed since the plan was read", 412, "prepare")
        await at("code")
        meta: Dict[str, Any] = dict(plan.code_meta)
        if plan.rung == ladder.RUNG_CARRIED:
            path = os.path.join(work, "code.bundle")
            try:
                tips = await asyncio.to_thread(lambda: bundles.make_bundle(project["root"], path, known_tips=[], air_gap=air_gap, full=True))
            except bundles.BundleError as exc:
                raise MigrateError(exc.code, exc.detail, 409, "code") from exc
            if tips is None:
                raise MigrateError("nothing_to_carry", "the repository has no branches to carry", 409, "code")
            meta["blob_id"] = await _send(request, path, "bundle")
        elif plan.rung == ladder.RUNG_TAR:
            path = os.path.join(work, "code.tar.zst")
            try:
                await asyncio.to_thread(tarball.make_tarball, project["root"], path)
            except tarball.TarballError as exc:
                raise MigrateError(exc.code, str(exc), 409, "code") from exc
            meta["blob_id"] = await _send(request, path, "tar")
        await at("rows")
        mpath = os.path.join(work, "manifest.json")
        with open(mpath, "w", encoding="utf-8") as handle:
            json.dump(plan.manifest, handle, default=str)
        os.chmod(mpath, 0o600)
        manifest_blob = await _send(request, mpath, "manifest")
        await at("transcripts")
        transcripts_blob = None
        if plan.files:
            tpath = os.path.join(work, "transcripts.tar.gz")
            await asyncio.to_thread(transcripts.build_archive, plan.files, tpath)
            transcripts_blob = await _send(request, tpath, "transcripts")
        received = await call(request, RECEIVE, {"op_id": op_id, "rung": plan.rung, "code": meta, "manifest_blob_id": manifest_blob,
                                                 "transcripts_blob_id": transcripts_blob, "air_gap": air_gap, "source_root": project["root"]}, "receive")
        if plan.rung == ladder.RUNG_UNITS and plan.carry is not None:
            await at("code")
            await _carry_units(request, plan, op_id, work, air_gap)
        await at("verify")
        verdict = await call(request, VERIFY, {"op_id": op_id}, "verify")
        if not verdict.get("ok"):
            raise MigrateError("verify_failed", "the project did not arrive intact: " + ", ".join(verdict.get("misses", [])), 409, "verify")
        await _db(env, lambda c: ops.update(c, op_id, "source", state="verifying", step="flip", detail={"summary": received.get("summary")}))
        return Staged(op_id, plan)
    except MigrateError as exc:
        if exc.step not in ("prepare",) or exc.code == "plan_changed":
            await _abort_target(request, op_id)
        await _db(env, lambda c: ops.update(c, op_id, "source", state="failed", step=exc.step or step, error_code=exc.code, detail={"error": exc.detail}))
        exc.step = exc.step or step
        raise
    except asyncio.CancelledError:
        await _abort_target(request, op_id)
        await _db(env, lambda c: ops.update(c, op_id, "source", state="failed", step=step, error_code="cancelled"))
        logger.info("pack_migrate_cancelled", op_id=op_id, step=step)
        raise
    except Exception:
        await _abort_target(request, op_id)
        await _db(env, lambda c: ops.update(c, op_id, "source", state="failed", step=step, error_code="internal"))
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def flip_project(env: SourceEnv, staged: Staged, request: Request, *, hold: bool = False) -> Dict[str, Any]:
    plan, op_id = staged.plan, staged.op_id
    try:
        answer = await call(request, FLIP, {"op_id": op_id}, "flip")
    except MigrateError as exc:
        await _abort_target(request, op_id)
        await _db(env, lambda c: ops.update(c, op_id, "source", state="failed", step="flip", error_code=exc.code))
        raise
    await _db(env, lambda c: home.set_state(c, plan.project["id"], home.MOVED_AWAY, moved_to_install_id=plan.target_install_id))
    await _db(env, lambda c: ops.update(c, op_id, "source", state="applying" if hold else "flipped", step="wake" if hold else "flip", detail={"reinstall_failed": answer.get("reinstall_failed", [])}))
    logger.info("pack_migrate_flipped", op_id=op_id, project_uid=plan.project["uid"], machine=plan.target_label, rung=plan.rung)
    return {"op_id": op_id, "project": plan.project["display_name"], "machine": plan.target_label, "root": answer.get("root"),
            "reinstall_failed": answer.get("reinstall_failed", [])}


async def apply_project(env: SourceEnv, plan: Plan, request: Request, *, op_id: Optional[str] = None, hold: bool = False) -> Dict[str, Any]:
    request = guarded(request)
    staged = await stage_project(env, plan, request, op_id=op_id)
    inflight.lock(staged.op_id, "flip")
    return await flip_project(env, staged, request, hold=hold)


async def apply_company(env: SourceEnv, plans: List[Plan], request: Request, *, company_uid: str, op_id: Optional[str] = None, hold: bool = False) -> Dict[str, Any]:
    request, op_id = guarded(request), op_id or ops.new_id()
    first = plans[0]
    await open_op(env, op_id, kind="company", subject_uid=company_uid, source_install_id=env.install_id,
                  target_install_id=first.target_install_id, step="stage",
                  detail={"name": (first.manifest["company"] or {}).get("name"), "projects": len(plans)})
    staged: List[Staged] = []
    try:
        for plan in plans:
            staged.append(await stage_project(env, plan, request, parent_id=op_id))
    except MigrateError as exc:
        for done in staged:
            await _abort_target(request, done.op_id)
            await _db(env, lambda c, d=done: ops.update(c, d.op_id, "source", state="failed", step="abort", error_code="company_aborted"))
        await _db(env, lambda c: ops.update(c, op_id, "source", state="failed", step="stage", error_code=exc.code, detail={"error": exc.detail}))
        raise
    except asyncio.CancelledError:
        for done in staged:
            await _abort_target(request, done.op_id)
            await _db(env, lambda c, d=done: ops.update(c, d.op_id, "source", state="failed", step="abort", error_code="company_aborted"))
        await _db(env, lambda c: ops.update(c, op_id, "source", state="failed", step="stage", error_code="cancelled"))
        raise
    results: List[Dict[str, Any]] = []
    try:
        inflight.lock(op_id, "flip")
        await _db(env, lambda c: ops.update(c, op_id, "source", step="flip"))
        for done in staged:
            results.append(await flip_project(env, done, request))
    except MigrateError as exc:
        for rest in staged[len(results):]:
            await _abort_target(request, rest.op_id)
        await _db(env, lambda c: ops.update(c, op_id, "source", state="failed", step="flip", error_code=exc.code, detail={"flipped": len(results)}))
        raise
    await _db(env, lambda c: ops.update(c, op_id, "source", state="applying" if hold else "flipped", step="wake" if hold else "flip"))
    return {"op_id": op_id, "projects": results}

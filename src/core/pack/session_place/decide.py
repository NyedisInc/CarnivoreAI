
from __future__ import annotations

import asyncio
from contextlib import closing
import dataclasses
from typing import Any, Collection, Dict, Tuple

from src.core.pack.identity import replicas
from src.core.pack.jobs import boot, needs_policy, place, policy as policy_mod
from src.core.pack.jobs.types import JobError
from src.core.project_writes import ProjectNameAmbiguous, ProjectNotFound, resolve_by_name
from src.core.pack.placement.workload import KIND_SESSION
from src.core.pack.session_place import plan as plan_mod
from src.core.pack.session_place.types import PlaceRequest, SessionPlacement


def _project_of(req: PlaceRequest, engine: Any) -> Tuple[str, str, str]:
    if req.project:
        try:
            with closing(engine._open_db()) as conn:  # noqa: SLF001
                row = resolve_by_name(conn, req.project)
        except ProjectNotFound as exc:
            raise JobError("project_unknown", f"no project named {req.project[:64]}", 404) from exc
        except ProjectNameAmbiguous as exc:
            raise JobError("project_ambiguous", f"more than one project is named {req.project[:64]}", 409) from exc
        if not row.get("uid"):
            raise JobError("project_unknown", "the project has no uid yet", 404)
        return str(row["uid"]), str(row["display_name"]), str(row["root"])
    if not req.working_dir:
        raise JobError("bad_request", "name the project or a folder inside it", 422)
    found, why = engine._resolve_project(req.working_dir)  # noqa: SLF001
    if found is None:
        raise JobError("project_unknown", why, 404)
    return found["uid"], found["name"], found["root"]


def _copies(engine: Any, uid: str) -> Dict[str, str]:
    with closing(engine._open_db()) as conn:  # noqa: SLF001
        rows = replicas.list_replicas(conn, uid)
    return {r["install_id"]: r["root"] for r in rows if r.get("root") and r.get("state", "active") == "active"}


def _read(req: PlaceRequest, exclude: Collection[str] = ()) -> SessionPlacement:
    engine = boot.engine()
    uid, name, root = _project_of(req, engine)
    pol = policy_mod.get(engine.store, uid)
    stored_needs, stored_prefer = needs_policy.get(engine.store, uid, KIND_SESSION)
    try:
        strict = plan_mod.merge_needs(req.needs, stored_needs)
        prefer = plan_mod.merge_needs([], stored_prefer)
    except ValueError as exc:
        raise JobError("bad_needs", str(exc), 422) from exc
    try:
        view = engine._view_for(root, uid)  # noqa: SLF001
    except JobError as exc:
        if exc.code != "pack_not_running":
            raise
        return SessionPlacement("here", plan_mod.clip(exc.detail), project_uid=uid, project_name=name)
    if exclude:
        view = dataclasses.replace(view, peers=[p for p in view.peers if p.install_id not in exclude])
    answer = plan_mod.plan(req, pol, view, strict, _copies(engine, uid), prefer=prefer)
    answer.project_name = name
    return answer


async def decide(app: Any, req: PlaceRequest, *, exclude: Collection[str] = ()) -> SessionPlacement:
    return await asyncio.to_thread(_read, req, tuple(exclude))


def _still_allowed(req: PlaceRequest, install_id: str) -> str:
    engine = boot.engine()
    uid, _name, root = _project_of(req, engine)
    pol = policy_mod.get(engine.store, uid)
    if not pol.auto_delegate:
        return "the project is no longer set to auto"
    view = engine._view_for(root, uid)  # noqa: SLF001
    if not view.self_input.is_home:
        return "this computer is no longer the project's home"
    peer = next((p for p in view.peers if p.install_id == install_id), None)
    if peer is None:
        return "that computer is no longer in the pack"
    why = place.drop_reason(peer, pol, view)
    return f"{peer.label} {why}" if why else ""


async def still_allowed(req: PlaceRequest, install_id: str) -> str:
    try:
        return await asyncio.to_thread(_still_allowed, req, install_id)
    except JobError as exc:
        return exc.detail or exc.code

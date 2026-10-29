from __future__ import annotations

import asyncio
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api import session_crud_routes
from src.api.auth import require_auth
from src.api.automation_routes import get_scheduler, get_store, refuse
from src.core.automations import delivered, gates
from src.core.automations.models import AutomationInvalid, AutomationNotFound
from src.core.automations.scrooge.fixit import FixRefused, plan_fix
from src.core.session_resume_target import CONVERSATION_RESUMED, ResumeTarget, resume_extra_args
from src.models.session_requests import CreateSessionRequest

router = APIRouter(prefix="/automations", tags=["automations"], dependencies=[Depends(require_auth)])


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str):
    """One run with its full report; a recorded alert (``delivered``) also carries ``state`` and ``state_at`` read live."""
    try:
        return await asyncio.to_thread(lambda: delivered.with_state(get_store(request).run(run_id)))
    except AutomationNotFound as exc:
        raise refuse(exc) from exc


@router.post("/runs/{run_id}/cancel")
async def cancel_run(request: Request, run_id: str):
    """Cancel a live run. 409 ``not_live`` when it already ended."""
    try:
        return await get_scheduler(request).cancel_run(run_id)
    except (AutomationInvalid, AutomationNotFound) as exc:
        raise refuse(exc) from exc


@router.post("/runs/{run_id}/findings/{finding_id}/fix")
async def start_fix_session(request: Request, run_id: str, finding_id: str):
    """Open a Claude session in the finding's project folder with its fix prompt loaded; returns the created session.

    404 ``run_not_found`` / ``finding_not_found``; 409 ``no_report``; 422 ``no_fix_prompt``, ``project_folder_missing``, ``home_folder``.
    """
    store = getattr(request.app.state, "automation_store", None)
    if store is None:
        raise HTTPException(503, detail={"code": "automations_unavailable"})
    try:
        run = store.run(run_id)
    except AutomationNotFound as exc:
        raise HTTPException(404, detail={"code": "run_not_found"}) from exc
    try:
        folder, prompt, label = plan_fix(run, finding_id)
    except FixRefused as exc:
        status = {"finding_not_found": 404, "no_report": 409}.get(exc.code, 422)
        raise HTTPException(status, detail={"code": exc.code}) from exc
    return await session_crud_routes.create_session(request, CreateSessionRequest(working_dir=folder, opening_prompt=prompt, label=label))


@router.post("/runs/{run_id}/continue")
async def continue_run_in_session(request: Request, run_id: str):
    """Open a Carnivore session that resumes a cron agent run's conversation, in the agent's folder and under its login.

    ``--resume`` is built once, by ``resume_extra_args``. 404 ``run_not_found``; 409 ``not_an_agent_run``, ``no_conversation``,
    ``automation_gone`` (the login is read from the automation); 422 ``folder_missing``. Returns the created session.
    """
    store = get_store(request)
    try:
        run = await asyncio.to_thread(store.run, run_id)
    except AutomationNotFound as exc:
        raise HTTPException(404, detail={"code": "run_not_found"}) from exc
    report = run.get("report")
    if not isinstance(report, dict) or "conversation_uuid" not in report:
        raise HTTPException(409, detail={"code": "no_conversation"})
    try:
        automation = await asyncio.to_thread(store.get, run["automation_id"])
    except AutomationNotFound as exc:
        raise HTTPException(409, detail={"code": "automation_gone"}) from exc
    if automation["target"].get("kind") != "agent":
        raise HTTPException(409, detail={"code": "not_an_agent_run"})
    try:
        conversation = str(uuid.UUID(str(report["conversation_uuid"])))
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "no_conversation"}) from exc
    folder = report.get("folder")
    if not isinstance(folder, str) or not os.path.isdir(folder):
        raise HTTPException(422, detail={"code": "folder_missing"})
    from src.core.byoai.contracts import ByoaiError  # noqa: PLC0415

    try:
        account_id, _profile = await asyncio.to_thread(gates.login_of, automation["target"])
    except ByoaiError as exc:
        raise HTTPException(409, detail={"code": "login_gone"}) from exc
    extra = resume_extra_args(ResumeTarget(CONVERSATION_RESUMED, conversation))
    label = f"{automation['name']} (continued)"[:120]
    return await session_crud_routes.create_session_with_extra(
        request, CreateSessionRequest(working_dir=folder, label=label), agent_extra_args=extra, claude_account=account_id)

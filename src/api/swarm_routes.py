
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Literal, NoReturn, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from src.api.auth import require_auth
from src.api.swarm_switch_routes import require_swarm_on
from src.core import db, session_change_notice, single_flight
from src.core.ttl_flight import TtlFlight
from src.core.swarm import answers, body, fact_life, company_agent, company_promote, create, export as swarm_export, facts, leaders, memory, owner_message, profiles, project_agent, project_promote, promotion, rename as swarm_rename, rewind, routing, settings as swarm_settings, promotion_store, store, stream, thread_port, turn_off, views
from src.core.swarm.body import BodyError
from src.models.swarm import (
    SwarmAgentDetail, SwarmCheckpointList, SwarmConversationPage, SwarmEarlierConversation, SwarmCreateRequest, SwarmFact, SwarmFactScope, SwarmKillResponse, SwarmMemoryCleanupResponse, SwarmMessageResponse,
    SwarmLookRequest, SwarmOwnerMessage, SwarmProjectSettings, SwarmPromoteRequest, SwarmQuestion, SwarmRewindRequest, SwarmRenameRequest, SwarmRoster, SwarmSettings, SwarmSleepResponse, SwarmTurnOffRequest, SwarmTurnOnRequest, SwarmWakeRequest,
    SwarmWakeResponse,
)

logger = structlog.get_logger()


def _require_port() -> None:
    if thread_port.get() is None:
        raise HTTPException(status_code=409, detail={"code": "swarm_off", "message": "the huddle plugin is off"})


router = APIRouter(prefix="/swarm", tags=["swarm"], dependencies=[Depends(require_auth)])
NEEDS_PORT = [Depends(_require_port)]
NEEDS_ON = NEEDS_PORT + [Depends(require_swarm_on)]


def _missing() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "agent_not_found", "message": "no such agent"})


def _refused(exc: Exception) -> NoReturn:
    if isinstance(exc, owner_message.SwarmOff):
        raise HTTPException(status_code=409, detail={"code": "swarm_off", "message": str(exc)}) from exc
    if isinstance(exc, BodyError):
        raise HTTPException(status_code=409, detail={"code": "swarm_refused", "message": str(exc)}) from exc
    raise HTTPException(status_code=503, detail={"code": "datastore_unreadable", "message": "the datastore could not be read"}) from exc


def _manager(request: Request) -> Any:
    return request.app.state.session_manager


ROSTER_BODIES_CACHE: TtlFlight = TtlFlight("swarm_roster_bodies", 1.0)


class _RosterBodies:

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    async def list_session_infos(self) -> List[Any]:
        manager = self._manager
        flight = single_flight.flight_on(manager, single_flight.SESSION_LIST_FLIGHT_ATTR, single_flight.SESSION_LIST_FLIGHT_NAME)
        return list(await ROSTER_BODIES_CACHE.get(lambda: flight.run(manager.list_session_infos)))


@router.get("/roster", response_model=SwarmRoster)
async def get_roster(request: Request) -> Dict[str, Any]:
    """Every live agent oldest first, each with its body's ``ses_`` id when awake, and the body caps.

    Answers with the Task Manager plugin off too (``threads_ready`` false): the Swarm page draws its empty state from that flag.
    """
    try:
        return await views.roster(_RosterBodies(_manager(request)))
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


@router.get("/agents/{agent_id}", response_model=SwarmAgentDetail, dependencies=NEEDS_PORT)
async def get_agent(agent_id: int, request: Request) -> Dict[str, Any]:
    """One agent in full: goal, effort reason, live children, open wake and its body when awake. 404 when unknown."""
    try:
        return await views.detail(_manager(request), agent_id)
    except views.AgentMissing:
        raise _missing() from None
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


@router.patch("/agents/{agent_id}", response_model=SwarmAgentDetail, dependencies=NEEDS_ON)
async def patch_agent(agent_id: int, payload: SwarmLookRequest, request: Request) -> Dict[str, Any]:
    """Set a node's own look, any subset (#1452): ``color_slot`` 1 to 8 is hand-set and wins over the family, null is auto again;
    ``shape`` beats the tier default, null is the default; ``tile_bg`` 1 to 8 is a tile background, null is none. 422 for a value
    outside those or an empty body; 404 when the agent is unknown or torn down. Answers the agent in full."""
    try:
        agent = await views.get_agent_row(agent_id)
        if agent["torn_down_at"] is not None:
            raise _missing()
        updates = payload.updates()
        await body.run_db(lambda c: store.update_agent(c, agent_id, **updates))
        return await views.detail(_manager(request), agent_id)
    except (views.AgentMissing, store.AgentNotFound):
        raise _missing() from None
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


@router.post("/agents", response_model=SwarmAgentDetail, status_code=201, dependencies=NEEDS_ON)
async def create_agent(body_in: SwarmCreateRequest, request: Request) -> Dict[str, Any]:
    """Create an asleep agent (rank ``feature`` or ``task``) in a folder; its body starts at the first wake or message.

    Raises: 422 ``invalid_agent`` (relative folder, a file in the way, a missing parent), 409 ``swarm_refused``
      (the slug race was lost), 503 (the datastore cannot be read).
    """
    try:
        agent = await create.create_agent(body_in.model_dump())
    except create.CreateInvalid as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_agent", "message": str(exc)}) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={"code": "swarm_refused", "message": "that agent already exists"}) from exc
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
    return await views.detail(_manager(request), agent["id"])


@router.post("/projects/{project_id}/agent", response_model=SwarmAgentDetail, status_code=201, dependencies=NEEDS_ON)
async def turn_on_project_agent(project_id: int, request: Request, payload: Optional[SwarmTurnOnRequest] = None) -> Dict[str, Any]:
    """Turn on a project's agent: its row, its thread (the project's own list) and one wake to propose a naming family.

    A folder that is not a git repo gets ``git init`` here: the turn-on is the owner's yes (#1434). A missing folder, the home
    folder, a system folder or one inside another repo is refused with the reason and nothing is written.
    The wake's orders ask the agent for a naming family and persona (``swarm_propose_naming``); until the owner approves
    that card, its children get plain job names. Turning on again after a failed first wake retries the wake.
    Raises: 404 ``project_not_found``, 422 ``invalid_agent`` (an unknown ``launch_profile``, nothing written), 409 ``swarm_refused`` (already on, git init refused, or the wake failed),
      503 (the datastore cannot be read).
    """
    try:
        agent = await project_agent.turn_on(request.app.state, project_id, (payload or SwarmTurnOnRequest()).launch_profile)
    except profiles.ProfileRefused as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_agent", "message": str(exc)}) from exc
    except project_agent.ProjectMissing as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": str(exc)}) from exc
    except project_agent.TurnOnError as exc:
        raise HTTPException(status_code=409, detail={"code": "swarm_refused", "message": str(exc)}) from exc
    except (BodyError, db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
    return await views.detail(_manager(request), agent["id"])


@router.post("/projects/{project_id}/promote", response_model=SwarmAgentDetail, dependencies=NEEDS_ON)
async def promote_session_to_project_agent(project_id: int, payload: SwarmPromoteRequest, request: Request) -> Dict[str, Any]:
    """Make an existing session the project's agent without a new session (``project_promote.py``, issue #1789).

    A running session is put to sleep and woken again resuming its conversation; an asleep one stays asleep. A project that already
    has an agent has it re-pointed to this session. Raises: 404 ``project_not_found``, 409 ``swarm_refused`` (a session that is deleted,
    another project's, a busy turn, already another agent ...: nothing changed), 503 (the datastore cannot be read).
    """
    try:
        agent = await project_promote.promote_session(request.app.state, payload.session_uuid, project_id)
    except project_agent.ProjectMissing as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": str(exc)}) from exc
    except project_agent.TurnOnError as exc:
        raise HTTPException(status_code=409, detail={"code": "swarm_refused", "message": str(exc)}) from exc
    except (BodyError, db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
    return await views.detail(_manager(request), agent["id"])


@router.post("/companies/{company_id}/agent", response_model=SwarmAgentDetail, status_code=201, dependencies=NEEDS_ON)
async def turn_on_company_agent(company_id: int, request: Request, payload: Optional[SwarmTurnOnRequest] = None) -> Dict[str, Any]:
    """Turn on a company's agent: its HQ repo ``<projects folder>/<Company> HQ`` (git init, filed as a project of the company),
    its row, its own thread and one wake. An HQ folder that already exists is refused with the reason, never adopted.

    Raises: 404 ``company_not_found``, 422 ``invalid_agent`` (an unknown ``launch_profile``, nothing written), 409 ``swarm_refused`` (already on, the HQ folder is in the way, git failed, or the wake
      failed: the row stays asleep and a second POST wakes it again), 503 (the datastore cannot be read).
    """
    try:
        agent = await company_agent.turn_on(request.app.state, company_id, (payload or SwarmTurnOnRequest()).launch_profile)
    except profiles.ProfileRefused as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_agent", "message": str(exc)}) from exc
    except company_agent.CompanyMissing as exc:
        raise HTTPException(status_code=404, detail={"code": "company_not_found", "message": str(exc)}) from exc
    except project_agent.TurnOnError as exc:
        raise HTTPException(status_code=409, detail={"code": "swarm_refused", "message": str(exc)}) from exc
    except (BodyError, db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
    return await views.detail(_manager(request), agent["id"])


@router.post("/companies/{company_id}/promote", response_model=SwarmAgentDetail, dependencies=NEEDS_ON)
async def promote_session_to_company_agent(company_id: int, payload: SwarmPromoteRequest, request: Request) -> Dict[str, Any]:
    """Make an existing session of the company's HQ project the company agent, no new session (``company_promote.py``, issue #1789).

    A running session is put to sleep and woken again resuming its conversation; an asleep one stays asleep. A company that already
    has an agent has it re-pointed to this session. Raises: 404 ``company_not_found`` or ``project_not_found``, 409 ``swarm_refused`` (no HQ
    project, a session that is deleted, another project's, a busy turn, already another agent ...: nothing changed), 503 (the datastore cannot be read).
    """
    try:
        agent = await company_promote.promote_session(request.app.state, payload.session_uuid, company_id)
    except company_agent.CompanyMissing as exc:
        raise HTTPException(status_code=404, detail={"code": "company_not_found", "message": str(exc)}) from exc
    except project_agent.ProjectMissing as exc:
        raise HTTPException(status_code=404, detail={"code": "project_not_found", "message": str(exc)}) from exc
    except project_agent.TurnOnError as exc:
        raise HTTPException(status_code=409, detail={"code": "swarm_refused", "message": str(exc)}) from exc
    except (BodyError, db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
    return await views.detail(_manager(request), agent["id"])


def _muted_categories(request: Request) -> Optional[List[str]]:
    store = getattr(request.app.state, "ui_preferences_store", None)
    value = None if store is None else store.read()["values"].get("swarm_chat_muted")
    return value if isinstance(value, list) else None


@router.get("/agents/{agent_id}/conversation", response_model=SwarmConversationPage, dependencies=NEEDS_PORT)
async def get_conversation(agent_id: int, request: Request, since: Optional[str] = Query(None, max_length=64),
                           limit: int = Query(stream.MAX_LIMIT, ge=1, le=stream.MAX_LIMIT),
                           view: Literal["all", "shown"] = Query("all")) -> Dict[str, Any]:
    """The agent's thread, oldest first: owner and agent messages and the Task Manager cards the owner acts on.

    Inputs: since (an entry id: only later entries); limit (1 to 200: the newest that many); view (``all`` is every entry,
    ``shown`` drops the categories the owner muted in ``ui_preferences.swarm_chat_muted``). ``cursor`` is the newest id.
    """
    try:
        muted = await asyncio.to_thread(_muted_categories, request) if view == "shown" else None
        return await stream.page(await views.get_agent_row(agent_id), since=since, limit=limit, view=view, muted=muted)
    except views.AgentMissing:
        raise _missing() from None
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


@router.post("/agents/{agent_id}/messages", response_model=SwarmMessageResponse, dependencies=NEEDS_ON)
async def post_message(agent_id: int, payload: SwarmOwnerMessage, request: Request) -> Dict[str, Any]:
    """An owner order to an agent: posted on its thread, then delivered (a sleeping agent is woken and the words ride its wake).

    Raises: 404 unknown agent, 409 ``swarm_refused`` (torn down, over a cap, the wake failed, or the body refused for good).
    """
    try:
        await views.get_agent_row(agent_id)
        sent = await owner_message.post_owner_message(request.app.state, agent_id, payload.text)
    except views.AgentMissing:
        raise _missing() from None
    except (BodyError, db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
    return {"message_ref": sent.message_ref, "outcome": sent.outcome}


@router.post("/agents/{agent_id}/wake", response_model=SwarmWakeResponse, dependencies=NEEDS_ON)
async def wake_agent(agent_id: int, request: Request, payload: Optional[SwarmWakeRequest] = None) -> Dict[str, Any]:
    """Wake an agent, or join the wake already running (``joined``); never starts a second body.

    ``mode`` ``fresh`` starts a new conversation, ``resume`` continues the last (a fresh wake when there is none).
    ``conversation_uuid`` resumes that earlier conversation (one of the agent's own, transcript on disk, agent asleep).
    Raises: 404 unknown agent, 409 ``swarm_refused`` (torn down, going to sleep, over a cap, or the start failed).
    """
    payload = payload or SwarmWakeRequest()
    try:
        await views.get_agent_row(agent_id)
        woke = await body.wake(request.app.state, agent_id, "manual", "data", mode=payload.mode,
                               conversation_uuid=payload.conversation_uuid)
    except views.AgentMissing:
        raise _missing() from None
    except (BodyError, db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
    return {"state": woke.state, "wake_id": woke.wake_id, "joined": not woke.started}


@router.post("/agents/{agent_id}/sleep", response_model=SwarmSleepResponse, dependencies=NEEDS_PORT)
async def sleep_agent(agent_id: int, request: Request) -> Dict[str, Any]:
    """Put an awake agent to sleep: stop its body, close its wake, commit its memory paths. Asleep already answers asleep.

    Raises: 404 unknown agent, 409 ``swarm_refused`` (a wake is still starting, or the body would not close).
    """
    try:
        await views.get_agent_row(agent_id)
        slept = await body.sleep(request.app.state, agent_id, "sleep")
    except views.AgentMissing:
        raise _missing() from None
    except (BodyError, db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
    commit = slept.commit or {}
    return {"state": slept.state, "commit": {"status": commit.get("status"), "sha": commit.get("sha") or None,
                                             "skipped_reason": commit.get("reason") or None}}


@router.post("/agents/{agent_id}/turn-off", response_model=SwarmSleepResponse, dependencies=NEEDS_PORT)
async def turn_off_agent(agent_id: int, request: Request, payload: Optional[SwarmTurnOffRequest] = None) -> Dict[str, Any]:
    """Turn an agent off: sleep its body (the memory commit runs), close its open cards, tombstone it. Its files and thread stay.

    Owner only; no MCP tool calls this. Answers ``state`` ``torn_down`` and the sleep's commit outcome.
    A company or project leader needs ``confirm_name`` equal to its display name (409 ``leader_protected`` otherwise, nothing changed).
    Raises: 404 ``agent_not_found`` (unknown or already off), 409 ``swarm_refused`` (Alpha, an agent with live children named in the
      message, a wake still starting, or the body would not close: nothing changed), 409 ``leader_protected``, 503 (the datastore cannot be read).
    """
    try:
        agent = await views.get_agent_row(agent_id)
        if agent["torn_down_at"] is None and agent["rank"] in ("company", "project") and not leaders.confirm_matches(agent, payload.confirm_name if payload else None):
            raise leaders.refusal(agent, "turn off")
        done = await turn_off.run(request.app.state, agent_id)
    except (store.AgentNotFound, views.AgentMissing):
        raise _missing() from None
    except (BodyError, db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
    commit = done["commit"] or {}
    return {"state": done["state"], "commit": {"status": commit.get("status"), "sha": commit.get("sha") or None,
                                               "skipped_reason": commit.get("reason") or None}}


@router.put("/agents/{agent_id}/name", response_model=SwarmAgentDetail, dependencies=NEEDS_ON)
async def rename_agent(agent_id: int, payload: SwarmRenameRequest, request: Request) -> Dict[str, Any]:
    """Rename any live agent (the owner; agents use the ``swarm_rename`` tool, which parks for the owner's approval), at any time.

    Changes the display name on the row, the sessions label (the drawer follows) and ``swarm.json``; the id, slug, memory, cards,
    thread, project and company stay, and ``agents_lookup`` by the old name still resolves (``former_names``). The naming rules
    apply (issue #1444). Raises: 404 ``agent_not_found``, 422 ``invalid_name`` (empty, over 25 characters, a feat/fix/tweak
    first word, a credential, or another live agent of the same project holds it), 503.
    """
    try:
        updated = await swarm_rename.rename(agent_id, payload.display_name)
        detail = await views.detail(_manager(request), agent_id)
        if detail.get("session_id"):
            session_change_notice.publish(request.app.state, session_change_notice.build_rename_notice(
                session_id=detail["session_id"], new_name=updated["display_name"]))
        return detail
    except (views.AgentMissing, store.AgentNotFound):
        raise _missing() from None
    except swarm_rename.RenameRefused as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_name", "message": str(exc)}) from exc
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


@router.get("/agents/{agent_id}/facts", response_model=List[SwarmFact], dependencies=NEEDS_PORT)
async def get_agent_facts(agent_id: int) -> List[Dict[str, Any]]:
    """The agent's facts that are live or held (a killed fact is gone), newest first. 404 when the agent is unknown."""
    try:
        await views.get_agent_row(agent_id)
        return await body.run_db(lambda c: facts.list_for_agent(c, agent_id))
    except views.AgentMissing:
        raise _missing() from None
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


def _fact_missing() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "fact_not_found", "message": "no such fact"})


@router.delete("/facts/{fact_id}", response_model=SwarmKillResponse, dependencies=NEEDS_ON)
async def kill_fact(fact_id: str, request: Request) -> Dict[str, Any]:
    """Kill a fact (file removed, index row deleted); every question whose newest answer cited it reopens and is routed again.

    Raises: 404 ``fact_not_found``, 409 ``swarm_refused`` (already killed), 503 (the datastore cannot be read).
    """
    try:
        return {"reopened_question_ids": await answers.kill_fact(request.app.state, fact_id)}
    except facts.FactNotFound:
        raise _fact_missing() from None
    except facts.FactRefused as exc:
        raise HTTPException(status_code=409, detail={"code": "swarm_refused", "message": str(exc)}) from exc
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        _refused(exc)


@router.patch("/facts/{fact_id}", response_model=SwarmFact, dependencies=NEEDS_ON)
async def patch_fact(fact_id: str, payload: SwarmFactScope) -> Dict[str, Any]:
    """Change a fact's scope (craft or project). Raises: 404 ``fact_not_found``, 409 ``swarm_refused`` (killed or unreadable file)."""
    try:
        return await body.run_db(lambda c: facts.set_scope(c, fact_id, payload.scope))
    except facts.FactNotFound:
        raise _fact_missing() from None
    except (facts.FactRefused, facts.memory.SwarmFileError) as exc:
        raise HTTPException(status_code=409, detail={"code": "swarm_refused", "message": str(exc)}) from exc
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        _refused(exc)


@router.post("/memory/cleanup", response_model=SwarmMemoryCleanupResponse, dependencies=NEEDS_ON)
async def post_memory_cleanup(request: Request) -> Dict[str, Any]:
    """The one-time memory cleanup (Alex (example-owner), 2026-10-27, #2609): every live project agent is handed the prune order
    (woken when asleep), deletes by the memory bar with ``swarm_forget`` and posts "kept N, deleted M" on its own thread.

    Raises: 503 (the datastore cannot be read). Example: POST /api/v1/swarm/memory/cleanup -> {"agents": [4, 9], "refused": []}
    """
    try:
        return await fact_life.cleanup(request.app.state)
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


@router.get("/questions", response_model=List[SwarmQuestion], dependencies=NEEDS_PORT)
async def get_questions(state: Optional[str] = Query(None, pattern="^(routing|open|answered|reopened|closed)$")) -> List[Dict[str, Any]]:
    """Routed questions newest first with their askers and newest receipt; ``state`` narrows the list."""
    try:
        return await body.run_db(lambda c: routing.list_questions(c, state))
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


@router.post("/agents/{agent_id}/flip-back", response_model=SwarmAgentDetail, dependencies=NEEDS_ON)
async def flip_back_agent(agent_id: int, request: Request) -> Dict[str, Any]:
    """Flip a promoted feature agent back to a task agent: it is put to sleep, its memory moves back to local scope in one
    commit, and its next wake is fresh.

    Raises: 404 unknown agent, 409 ``swarm_refused`` (never promoted or already flipped back, the repo is mid-merge, a wake is starting).
    """
    try:
        await views.get_agent_row(agent_id)
        await promotion.flip_back(request.app.state, agent_id)
    except views.AgentMissing:
        raise _missing() from None
    except (promotion.PromotionRefused, BodyError) as exc:
        raise HTTPException(status_code=409, detail={"code": "swarm_refused", "message": str(exc)}) from exc
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
    return await views.detail(_manager(request), agent_id)


@router.get("/agents/{agent_id}/checkpoints", response_model=SwarmCheckpointList, dependencies=NEEDS_PORT)
async def get_checkpoints(agent_id: int) -> Dict[str, Any]:
    """The agent's memory checkpoints, newest first (at most 50); an empty list carries a ``reason`` (local memory is not in git).

    Raises: 404 unknown agent.
    """
    try:
        return await rewind.checkpoints(await views.get_agent_row(agent_id))
    except views.AgentMissing:
        raise _missing() from None
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


@router.post("/agents/{agent_id}/rewind", response_model=SwarmSleepResponse, dependencies=NEEDS_ON)
async def rewind_agent(agent_id: int, payload: SwarmRewindRequest, request: Request) -> Dict[str, Any]:
    """Restore the agent's memory folder to one of its checkpoints in a new commit; its next wake is fresh.

    Raises: 404 unknown agent, 409 ``swarm_refused`` (awake, local memory, not a checkpoint, the folder has uncommitted changes,
      the repo is mid-merge or detached, or the commit did not land; nothing is left half-applied).
    """
    try:
        await views.get_agent_row(agent_id)
        return await rewind.rewind(request.app.state, agent_id, payload.sha)
    except views.AgentMissing:
        raise _missing() from None
    except (rewind.RewindRefused, BodyError) as exc:
        raise HTTPException(status_code=409, detail={"code": "swarm_refused", "message": str(exc)}) from exc
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


@router.get("/agents/{agent_id}/export", dependencies=NEEDS_PORT, response_class=Response, responses={200: {"content": {"application/zip": {}}}})
async def export_agent(agent_id: int) -> Response:
    """The agent's craft-only export as ``application/zip`` (pick W): definition without project parts, craft facts, Codex twin, README.

    Raises: 404 unknown agent, 422 ``secret_found`` (names the file, never the value), 409 ``swarm_refused`` (torn down or its
      definition unreadable), 413 ``export_too_large``.
    """
    try:
        agent = await views.get_agent_row(agent_id)
        out_name, data = await body.run_db(lambda c: swarm_export.build_named_blocking(c, agent))
    except views.AgentMissing:
        raise _missing() from None
    except memory.SecretRefused as exc:
        raise HTTPException(status_code=422, detail={"code": "secret_found", "message": str(exc)}) from exc
    except swarm_export.ExportTooLarge as exc:
        raise HTTPException(status_code=413, detail={"code": "export_too_large", "message": str(exc)}) from exc
    except (swarm_export.ExportRefused, memory.SwarmFileError) as exc:
        raise HTTPException(status_code=409, detail={"code": "swarm_refused", "message": str(exc)}) from exc
    except OSError as exc:
        logger.warning("swarm_export_unreadable", agent_id=agent_id, error=type(exc).__name__)
        raise HTTPException(status_code=409, detail={"code": "swarm_refused",
                                                     "message": "a file the export needs could not be read"}) from exc
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{out_name}-craft.zip"'})


@router.get("/agents/{agent_id}/conversations", response_model=List[SwarmEarlierConversation], dependencies=NEEDS_PORT)
async def get_earlier_conversations(agent_id: int) -> List[Dict[str, Any]]:
    """The agent's earlier conversations, newest first, for ``POST .../wake`` with a ``conversation_uuid``.

    Raises: 404 unknown agent.
    """
    try:
        return await rewind.conversations(await views.get_agent_row(agent_id))
    except views.AgentMissing:
        raise _missing() from None
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


def _project_missing() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "project_not_found", "message": "no such project"})


@router.get("/projects/{project_id}/settings", response_model=SwarmProjectSettings)
async def get_project_settings(project_id: int) -> Dict[str, Any]:
    """The project's promotion threshold (5 when never set). Raises: 404 ``project_not_found``, 503 (datastore unreadable)."""
    try:
        return await body.run_db(lambda c: _project_threshold(c, project_id))
    except LookupError:
        raise _project_missing() from None
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


@router.put("/projects/{project_id}/settings", response_model=SwarmProjectSettings)
async def put_project_settings(project_id: int, payload: SwarmProjectSettings) -> Dict[str, Any]:
    """Set the project's promotion threshold (1 to 100). Raises: 404 ``project_not_found``, 503 (datastore unreadable)."""
    def write(conn: sqlite3.Connection) -> Dict[str, Any]:
        _project_threshold(conn, project_id)
        promotion_store.set_promotion_threshold(conn, project_id, payload.promotion_threshold)
        return {"promotion_threshold": payload.promotion_threshold}

    try:
        return await body.run_db(write)
    except LookupError:
        raise _project_missing() from None
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


def _project_threshold(conn: sqlite3.Connection, project_id: int) -> Dict[str, Any]:
    if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise LookupError(project_id)
    return {"promotion_threshold": promotion_store.promotion_threshold(conn, project_id)}


def _config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


@router.get("/settings", response_model=SwarmSettings)
async def get_settings() -> Dict[str, Any]:
    """The ``swarm`` block: the optional body caps, idle minutes, hop timeout and wake coverage (the defaults when absent)."""
    return (await asyncio.to_thread(swarm_settings.read_current)).model_dump()


@router.put("/settings", response_model=SwarmSettings)
async def put_settings(payload: SwarmSettings) -> Dict[str, Any]:
    """Change any of the Swarm settings (omit a field to leave it alone) through the one config writer.

    Raises: 500 ``config_unreadable`` when config.json is missing or not JSON.
    """
    changes = payload.model_dump(exclude_none=True)
    changes |= {k: None for k in swarm_settings.CLEARABLE if k in payload.model_fields_set and getattr(payload, k) is None}
    try:
        block = await asyncio.to_thread(swarm_settings.write_changes, _config_path(), changes)
    except (OSError, ValueError) as exc:
        logger.warning("swarm_settings_write_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail={"code": "config_unreadable",
                                                     "message": "config.json could not be used"}) from exc
    if "upper_ranks_permissions" in changes:
        await asyncio.to_thread(profiles.sync_posture)
    return block.model_dump()

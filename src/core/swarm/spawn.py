
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import structlog

from src.core.crosstalk import bus, store as crosstalk_store
from src.core.db import DatastoreUnreadableError
from src.core.mcp.caller import AgentCaller
from src.core.swarm import body, brief, create, effort as effort_floor, memory, naming_rules, profiles, slugs, promotion_store, store, switch
from src.core.swarm import settings as swarm_settings
from src.core.pack.placement import workload as pack_workload

logger = structlog.get_logger()

SPAWNER_RANKS = ("project",)
CHILD_RANKS = ("feature", "task")
HARNESSES = ("claude", "codex")
MAX_JOB_CHARS = 300
MAX_NAME_CHARS = naming_rules.MAX_NAME_CHARS
MAX_SPAWN_REASON_CHARS = 300
CONTACT_SOURCE = "swarm"


class SpawnRefused(ValueError):
    pass


class SpawnRedirect(SpawnRefused):

    def __init__(self, agent: Dict[str, Any]) -> None:
        self.agent = agent
        super().__init__(f"not spawned: {agent['display_name']} (agent {agent['id']}) is the live feature agent for "
                         f"{agent.get('specialty') or agent['display_name']}; send the work to it (deal it the card with swarm_card_deal), "
                         "or call swarm_spawn again with spawn_reason saying why a new agent is needed")

    def answer(self) -> Dict[str, Any]:
        a = self.agent
        return {"spawned": False, "detail": str(self),
                "suggested_agent": {"agent_id": a["id"], "display_name": a["display_name"], "specialty": a.get("specialty"), "state": a["state"]}}


class SpawnQueued(SpawnRefused):
    pass


@dataclass(frozen=True)
class SpawnPlan:

    parent: Dict[str, Any]
    request: Dict[str, Any]
    first_message: str
    target: Optional[Dict[str, Any]] = None
    card_id: Optional[int] = None
    workload: Optional[Dict[str, Any]] = None
    queue_id: Optional[int] = None
    machine: Optional[str] = None


def _text(args: Dict[str, Any], key: str, *, required: bool = True) -> str:
    value = args.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise SpawnRefused(f"{key} is required" if required else f"{key} must be text")
    return value.strip()


async def parent_agent(view: Any, caller: AgentCaller) -> Dict[str, Any]:
    if caller.external:
        raise SpawnRefused("swarm tools are for Swarm agents")
    if caller.proxied_agent_id:
        proxied = await body.run_db(lambda c: store.get_agent(c, caller.proxied_agent_id))
        if proxied is None or proxied["torn_down_at"] is not None:
            raise SpawnRefused("swarm tools are for Swarm agents")
        return proxied
    info = next((i for i in await view.list_session_infos()
                 if i.session.id == caller.current_session_id and i.tmux_session == caller.tmux_name), None)
    row_id = getattr(info, "session_row_id", None)
    agent = await body.run_db(lambda c: store.get_agent_by_session_row(c, row_id)) if row_id is not None else None
    if agent is None or agent["torn_down_at"] is not None:
        raise SpawnRefused("swarm tools are for Swarm agents")
    return agent


def _names(rank: str, job: str, name: str, specialty: str) -> Tuple[str, str]:
    try:
        specialty = naming_rules.check_name(specialty, "specialty") if specialty else ""
        if rank == "feature" and not specialty:
            raise naming_rules.NameRefused(f"specialty is required for a feature agent: the domain it owns. {naming_rules.RULES_TEXT}")
        if name:
            return naming_rules.check_name(name), specialty
    except naming_rules.NameRefused as exc:
        raise SpawnRefused(str(exc)) from None
    try:
        return naming_rules.check_name(specialty if rank == "feature" else job), specialty
    except naming_rules.NameRefused as exc:
        raise SpawnRefused(f"name is required: none was given and the job cannot be one ({exc})") from None


def _check_profile(name: str) -> None:
    try:
        profiles.require_known(name)
    except profiles.ProfileRefused as exc:
        raise SpawnRefused(str(exc)) from exc


async def _check_card(parent: Dict[str, Any], card_id: Any) -> None:
    from src.core.swarm.cards import permits, port as card_port

    if type(card_id) is not int or card_id < 1:
        raise SpawnRefused("card must be a card id from swarm_card_list")
    try:
        card = await card_port.get().card(card_id)
    except card_port.CardsOff:
        raise SpawnRefused("the huddle plugin is off, so there are no cards") from None
    if card is None:
        raise SpawnRefused(f"no card #{card_id}")
    if card["column"] not in ("todo", "in_progress") or card.get("holder"):
        raise SpawnRefused(f"card #{card_id} is not waiting in the queue")
    refusal = permits.check(parent, "deal", card, {})
    if refusal:
        raise SpawnRefused(refusal)


async def _give_card(app_state: Any, plan: "SpawnPlan", child: Dict[str, Any]) -> str:
    from src.core.swarm import facts
    from src.core.swarm.cards import ops, port as card_port, texts
    from src.cplugs.sdk.cards import CardRefused

    request = plan.request
    try:
        card_port.get()
        card = await ops.mint_for_spawn(app_state, plan.parent, child, title=request["job"], text=request.get("goal", ""), card_id=plan.card_id)
        if card is None:  # could not
            return ""
    except card_port.CardsOff:
        return ""
    except CardRefused as exc:
        raise SpawnRefused(f"the card could not be dealt: {exc}") from exc
    known = await facts.chain_facts_for(child["id"], f"{card.get('title') or ''} {card.get('text') or ''}")
    return texts.spawn_card_line(card, known)


async def prepare(view: Any, caller: AgentCaller, args: Dict[str, Any]) -> SpawnPlan:
    return await prepare_for(await parent_agent(view, caller), args)


async def prepare_for(parent: Dict[str, Any], args: Dict[str, Any]) -> SpawnPlan:
    if parent["rank"] not in SPAWNER_RANKS:
        raise SpawnRefused(f"a {parent['rank']} agent cannot spawn; only project agents spawn feature and task agents")
    rank = _text(args, "rank")
    if rank not in CHILD_RANKS:
        raise SpawnRefused("rank must be feature or task")
    job, goal = _text(args, "job"), _text(args, "goal")
    task_type = _text(args, "task_type")
    if not slugs.is_valid_slug(task_type):
        raise SpawnRefused("task_type must be a slug: lowercase letters, digits and dashes")
    if len(job) > MAX_JOB_CHARS:
        raise SpawnRefused(f"job must be at most {MAX_JOB_CHARS} characters")
    harness = _text(args, "harness", required=False) or "claude"
    if harness not in HARNESSES:
        raise SpawnRefused("harness must be claude or codex")
    try:
        effort, reason = effort_floor.resolve(_text(args, "effort", required=False), _text(args, "effort_reason", required=False))
    except effort_floor.EffortRefused as exc:
        raise SpawnRefused(str(exc)) from None
    persona, name = _text(args, "persona", required=False), _text(args, "name", required=False)
    specialty, why_new = _text(args, "specialty", required=False), _text(args, "spawn_reason", required=False)
    if len(why_new) > MAX_SPAWN_REASON_CHARS:
        raise SpawnRefused(f"spawn_reason must be at most {MAX_SPAWN_REASON_CHARS} characters")
    profile = _text(args, "launch_profile", required=False)
    if profile:
        await asyncio.to_thread(_check_profile, profile)
    target = await body.run_db(lambda c: promotion_store.promoted_agent(c, parent["id"], task_type))
    if target is None:
        if not name and parent["naming_state"] == "approved" and await asyncio.to_thread(swarm_settings.naming_family_on):
            raise SpawnRefused(f"name is required: give this agent a persona name from your approved naming family "
                               f"({parent.get('naming_family') or 'the family the owner approved'}), then call swarm_spawn again")
        name, specialty = _names(rank, job, name, specialty)
        if not why_new:
            found = await body.run_db(lambda c: naming_rules.specialist_for(c, parent, specialty or name))
            if found is not None:
                raise SpawnRedirect(found)
    try:
        first = brief.render_brief(brief.BriefSpec(
            slug="x", display_name="X", persona=persona or "a focused specialist", name_reason="x", job=job, rank="feature" if target else rank,
            order=job, goal=goal, effort=effort, effort_reason=reason, parent_name=parent["display_name"],
            memory_dir="m")).first_message
    except memory.SwarmFileError as exc:
        raise SpawnRefused(str(exc)) from exc
    request: Dict[str, Any] = {"repo_dir": parent["repo_dir"], "job": job, "rank": rank, "effort": effort,
                               "parent_id": parent["id"], "goal": goal, "task_type": task_type, "harness": harness}
    request.update({k: v for k, v in (("persona", persona), ("display_name", name), ("effort_reason", reason), ("launch_profile", profile),
                                      ("specialty", specialty if rank == "feature" else "")) if v})
    card_id = args.get("card")
    if card_id is not None:
        await _check_card(parent, card_id)
    tag = args.get("workload")
    if tag is not None:
        if not isinstance(tag, dict):
            raise SpawnRefused("workload must be an object: {kind, est_cpu_cores, est_ram_gb, est_disk_gb}")
        try:
            pack_workload.resolve(tag, task_type)
        except ValueError as exc:
            raise SpawnRefused(str(exc)) from None
    machine = _text(args, "machine", required=False) or None
    return SpawnPlan(parent, request, first, target, card_id, tag, machine=machine)


async def _retire(app_state: Any, plan: "SpawnPlan", child: Dict[str, Any]) -> None:
    if plan.target is not None:
        return
    try:
        await body.sleep(app_state, child["id"], "sleep")
    except body.BodyError as exc:
        logger.warning("swarm_spawn_card_sleep_failed", agent_id=child["id"], error=str(exc)[:200])
    await body.run_db(lambda c: store.tear_down(c, child["id"]))


async def _check_floors(parent: Dict[str, Any], profile: Optional[str]) -> None:
    from src.core.swarm.cards import capacity, port as card_port

    try:
        _, floors = await capacity.gate_inputs(parent.get("project_id"))
    except card_port.CardsOff:
        return
    code = await asyncio.to_thread(capacity.floor_refusal, profile) if floors else None
    if code:
        raise SpawnRefused(f"not spawned: {await asyncio.to_thread(capacity.refusal_text, code, profile)}")


_QUEUED_KEYS = ("job", "goal", "task_type", "rank", "effort", "effort_reason", "persona", "specialty", "launch_profile", "harness")


def _queue_args(plan: "SpawnPlan") -> Dict[str, Any]:
    args = {k: plan.request[k] for k in _QUEUED_KEYS if k in plan.request}
    if plan.request.get("display_name"):
        args["name"] = plan.request["display_name"]
    if plan.card_id is not None:
        args["card"] = plan.card_id
    if plan.workload is not None:
        args["workload"] = plan.workload
    if plan.machine:
        args["machine"] = plan.machine
    args["spawn_reason"] = "retried from the Pack spawn queue"
    return args


async def _place(plan: "SpawnPlan") -> Optional[Any]:
    if plan.target is not None:
        return None
    from src.core.pack.placement import explain, queue as spawn_queue

    try:
        work = explain.workload_for(plan.workload, plan.request.get("task_type"))
        decision = await explain.place(explain.Request(work, project=plan.parent.get("repo_dir"), machine=plan.machine), record_it=False)
    except explain.PlacementUnavailable:
        return None
    except ValueError as exc:
        raise SpawnRefused(f"not spawned: {exc}") from None
    except Exception as exc:  # noqa: BLE001
        logger.warning("swarm_spawn_placement_failed", error=type(exc).__name__)
        return None
    if decision.chosen is not None:
        return decision
    if plan.queue_id is None:
        request = {"parent_id": plan.parent["id"], "args": _queue_args(plan)}
        queue_id = await body.run_db(lambda c: spawn_queue.enqueue(c, request, decision.reason))
        await body._card(plan.parent, "queued", f"{plan.request['job']} is waiting for a computer with room: {decision.reason}.",
                         f"spawn_queued:{queue_id}")
    raise SpawnQueued(f"queued: {decision.reason}")


def _placed_remote(placed: Optional[Any]) -> bool:
    from src.core.pack.machines import runtime

    wired = runtime.wiring()
    return placed is not None and wired is not None and placed.chosen not in (None, wired.runtime.install_id)


async def _host_on(placed: Optional[Any], child: Dict[str, Any]) -> Dict[str, Any]:
    from src.core.pack.machines import runtime

    wired = runtime.wiring()
    if placed is None or wired is None or placed.chosen in (None, wired.runtime.install_id):
        return child
    from src.core.pack.span import remote_body

    try:
        peer = await asyncio.to_thread(remote_body.peer_for, placed.chosen)
    except RuntimeError as exc:
        raise SpawnRefused(f"not spawned: {exc}") from exc
    return await body.run_db(lambda c: store.update_agent(c, child["id"], host_key=peer.key))


async def _record_placement(decision: Any, child: Dict[str, Any]) -> None:
    from src.core.pack.placement import explain

    try:
        await body.run_db(lambda c: explain.record(c, decision, agent_id=child["id"]))
    except (sqlite3.Error, DatastoreUnreadableError) as exc:
        logger.warning("swarm_spawn_placement_record_failed", agent_id=child["id"], error=type(exc).__name__)


async def _start_child(app_state: Any, plan: SpawnPlan, *, mint_card: bool, orders: str = "") -> Tuple[Dict[str, Any], str]:
    """The part of a spawn both callers share: caps, the child row, its body and its card.

    Inputs: app_state; plan; mint_card (give the child a card: the named one, else one minted from the goal); orders (text written to the
      child's desk on its first wake). Output: ``(child row, the line the first message gains)``. Raises: SpawnRefused (a cap, a refused or
      failed start, a card that could not be dealt, or the global Swarm switch is off). A cap refusal also posts a card in the parent's thread.
    """
    if not switch.is_on():
        raise SpawnRefused(switch.OFF_MESSAGE)
    parent = plan.parent
    placed = await _place(plan)
    if plan.target is None:
        child_to_be = {"parent_id": parent["id"], "project_id": parent.get("project_id"), "rank": plan.request.get("rank")}
        work = pack_workload.resolve(plan.workload, plan.request.get("task_type")).as_dict()
        refusal = await body.run_db(lambda c: body.caps_refusal(c, child_to_be, workload=work, machine=not _placed_remote(placed)))
        if refusal:
            await body._card(parent, "cannot spawn yet", f"{parent['display_name']} could not start {plan.request['job']}: {refusal}.",
                             f"spawn_refused:{parent['id']}")
            raise SpawnRefused(f"not spawned: {refusal}")
    if mint_card:
        await _check_floors(parent, profiles.effective_profile(plan.target or {"harness": "claude", **plan.request}))
    child = plan.target or await create.create_agent(plan.request)
    if placed is not None:
        await _record_placement(placed, child)
        if plan.target is None:
            try:
                child = await _host_on(placed, child)
            except SpawnRefused:
                await body.run_db(lambda c: store.tear_down(c, child["id"]))
                raise
    try:
        await body.wake(app_state, child["id"], "spawn", "data", orders=orders)
    except body.BodyError as exc:
        if plan.target is None:
            await body.run_db(lambda c: store.tear_down(c, child["id"]))
        raise SpawnRefused(str(exc)) from exc
    try:
        card_line = await _give_card(app_state, plan, child) if mint_card else ""
    except (SpawnRefused, sqlite3.Error, DatastoreUnreadableError) as exc:
        await _retire(app_state, plan, child)
        if isinstance(exc, SpawnRefused):
            raise
        raise SpawnRefused(f"the card could not be dealt: {exc}") from exc
    return child, card_line


def _answer(plan: SpawnPlan, child: Dict[str, Any], message_id: Optional[str]) -> Dict[str, Any]:
    logger.info("swarm_spawned", parent_id=plan.parent["id"], agent_id=child["id"], rank=child["rank"], slug=child["slug"])
    return {"agent_id": child["id"], "slug": child["slug"], "display_name": child["display_name"], "state": "awake",
            "message_id": message_id, "routed_to_promoted": plan.target is not None}


async def run(view: Any, caller: AgentCaller, plan: SpawnPlan) -> Dict[str, Any]:
    """Create the child, start its body, grant the contact and deliver its first task.

    Inputs: view (BatchView carrying ``app``); caller (the parent's pane); plan (from :func:`prepare`).
    Output: ``{agent_id, slug, display_name, state, message_id, routed_to_promoted}``.
    Raises: SpawnRefused (a cap, a refused or failed start, a first message that could not be queued). A cap
      refusal also posts a card in the parent's thread. NO terminal tab is persisted beside the parent. With ``plan.target``
      (a promoted feature agent) nothing is created: it is woken and gets the order, and a failed wake leaves it asleep.
    """
    child, card_line = await _start_child(view.app.state, plan, mint_card=True)
    fresh = view.fresh()
    sender, receiver = await bus.identities(fresh, caller, f"agent:{child['id']}")
    await asyncio.to_thread(crosstalk_store.grant_contact, sender["key"], receiver["key"], sender["epoch"], receiver["epoch"],
                            source=CONTACT_SOURCE)
    sent = await bus.send(fresh.fresh(), caller, to=receiver["id"], text=plan.first_message + card_line, owner_approved=True,
                          action="swarm_spawn", source=CONTACT_SOURCE)
    return _answer(plan, child, sent["id"])


async def run_for(app_state: Any, plan: SpawnPlan, *, mint_card: bool = True) -> Dict[str, Any]:
    child, card_line = await _start_child(app_state, plan, mint_card=mint_card, orders=plan.first_message)
    if card_line:
        from src.core.swarm.cards import deliver

        await deliver.tell(app_state, child["id"], card_line.strip(), ref=f"spawn:{child['id']}")
    return _answer(plan, child, None)


def owner_summary(plan: SpawnPlan) -> str:
    where = f"goes to the feature agent {plan.target['display_name']}" if plan.target else f"parent {plan.parent['display_name']}"
    named = f" {plan.request['display_name']!r}" if plan.request.get("display_name") and not plan.target else ""
    return f"swarm_spawn {plan.request['rank']}{named}: {plan.request['job'][:160]} ({where})"


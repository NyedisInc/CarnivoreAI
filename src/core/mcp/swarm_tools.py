
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, get_args

import structlog

from src.core import db
from src.core.mcp.caller import AgentCaller
from src.core.mcp import lean_answers
from src.core.mcp.common import ToolError, _ok
from src.core.swarm.cards import ops, port as card_port
from src.cplugs.sdk.cards import CardRefused
from src.cplugs.sdk.storage import CplugSchemaError
from src.core.swarm import answers, body, brief, conflicts, facts, naming_rules, project_agent, promotion, receipts, rename, reports, rewind, routing, say, spawn, store, stream, suggest, views
from src.core.swarm import effort as effort_floor
from src.core.swarm.settings import LookShape

logger = structlog.get_logger()

DEFAULT_CONVERSATION_LIMIT = 20
DETAIL_CONVERSATION_LIMIT = 50


def _agent_id(args: dict) -> int:
    value = args.get("agent_id")
    if type(value) is not int or value < 1:
        raise ToolError("agent_id is required and must be a positive whole number")
    return value


async def _read(call: Any) -> dict:
    try:
        return _ok(await call)
    except views.AgentMissing:
        raise ToolError("no such agent") from None
    except (db.DatastoreUnreadableError, sqlite3.Error):
        raise ToolError("the Swarm datastore could not be read") from None


async def swarm_roster(manager: Any, caller: AgentCaller, args: dict) -> dict:
    full = lean_answers.detail_flag(args)

    async def read() -> dict:
        roster = await views.roster(manager)
        return roster if full else lean_answers.swarm_roster(roster)

    return await _read(read())


async def swarm_agent(manager: Any, caller: AgentCaller, args: dict) -> dict:
    return await _read(views.detail(manager, _agent_id(args)))


async def swarm_conversation(manager: Any, caller: AgentCaller, args: dict) -> dict:
    since = args.get("since")
    wide = lean_answers.detail_flag(args) or since is not None
    limit = args.get("limit", DETAIL_CONVERSATION_LIMIT if wide else DEFAULT_CONVERSATION_LIMIT)
    if type(limit) is not int or not 1 <= limit <= stream.MAX_LIMIT:
        raise ToolError(f"limit must be a whole number from 1 to {stream.MAX_LIMIT}")
    if since is not None and not isinstance(since, str):
        raise ToolError("since must be an entry id from an earlier read")

    async def read() -> dict:
        return await stream.page(await views.get_agent_row(_agent_id(args)), since=since, limit=limit)

    return await _read(read())


async def swarm_checkpoints(manager: Any, caller: AgentCaller, args: dict) -> dict:
    async def read() -> dict:
        return await rewind.checkpoints(await views.get_agent_row(_agent_id(args)))

    return await _read(read())


async def swarm_conversations(manager: Any, caller: AgentCaller, args: dict) -> dict:
    async def read() -> dict:
        return {"conversations": await rewind.conversations(await views.get_agent_row(_agent_id(args)))}

    return await _read(read())


async def swarm_rewind(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.core.mcp import write_tools

    agent_id, sha = _agent_id(args), args.get("sha")
    if not isinstance(sha, str) or not 7 <= len(sha) <= 40:
        raise ToolError("sha must be a checkpoint sha from swarm_checkpoints")

    async def go(_approved: bool) -> dict:
        try:
            return _ok(await rewind.rewind(manager.app.state, agent_id, sha))
        except (rewind.RewindRefused, body.BodyError) as exc:
            raise ToolError(str(exc)) from None
        except (db.DatastoreUnreadableError, sqlite3.Error):
            raise ToolError("the Swarm datastore could not be read") from None

    return await write_tools.park(manager, caller, caller.current_session_id, caller.tmux_name, "swarm_rewind",
                                  f"rewind Swarm agent {agent_id}'s memory folder to commit {sha[:8]} (in a new commit)",
                                  {"agent_id": agent_id, "sha": sha}, go, beast_eligible=False)


async def swarm_spawn(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.core.mcp import beast_mode, write_tools

    try:
        plan = await spawn.prepare(manager, caller, args)
    except spawn.SpawnRedirect as exc:
        return _ok(exc.answer())
    except spawn.SpawnRefused as exc:
        raise ToolError(str(exc)) from None

    async def go(_approved: bool) -> dict:
        try:
            return _ok(await spawn.run(manager.fresh(), caller, plan))
        except spawn.SpawnRefused as exc:
            raise ToolError(str(exc)) from None

    summary, shown = spawn.owner_summary(plan), {k: v for k, v in args.items() if isinstance(k, str)}
    if beast_mode.approval_skip("swarm_spawn"):
        return await beast_mode.run_unprompted(caller, "swarm_spawn", lambda: go(True), target_id=caller.current_session_id,
                                               target_tmux=caller.tmux_name, summary=summary, args=shown)
    return await write_tools.park(manager, caller, caller.current_session_id, caller.tmux_name, "swarm_spawn", summary,
                                  shown, go)


async def _held_cards(manager: Any, caller: AgentCaller) -> list:
    try:
        agent = await spawn.parent_agent(manager, caller)
        return await ops.held_cards(agent["id"])
    except (spawn.SpawnRefused, card_port.CardsOff):
        return []
    except (CplugSchemaError, sqlite3.Error, OSError) as exc:
        logger.warning("swarm_report_cards_unavailable", error=str(exc)[:200])
        return []


async def _finish_held(manager: Any, caller: AgentCaller, args: dict, held: list) -> dict:
    wanted = args.get("card")
    card = next((c for c in held if c["id"] == wanted), None) if wanted is not None else (held[0] if len(held) == 1 else None)
    if card is None:
        raise ToolError("you hold " + ", ".join(f"#{c['id']}" for c in held) + ": pass card with the id you are reporting")
    how = args.get("how_to_validate")
    if not isinstance(how, str) or not how.strip():
        raise CardRefused("no_how_to_validate", "write how to validate this card (steps the owner can run) before you report it")
    agent = await spawn.parent_agent(manager, caller)
    finished = await ops.finish(manager.app.state, card["id"], {"result": reports.report_text(args), "how_to_validate": how,
                                                              "validate_link": args.get("validate_link")}, by=f"agent:{agent['id']}")
    return {"card_id": finished["id"], "report_id": finished.get("report_id"), "state": "pending" if finished.get("report_id") else "review"}


async def swarm_report(manager: Any, caller: AgentCaller, args: dict) -> dict:
    try:
        held = await _held_cards(manager, caller)
        if held:
            return _ok(await _finish_held(manager, caller, args, held))
        return _ok(await reports.report(manager, caller, args))
    except reports.ReportRefused as exc:
        raise ToolError(str(exc)) from None
    except CardRefused as exc:
        raise ToolError(f"{exc.code}: {exc}") from None


async def swarm_accept_report(manager: Any, caller: AgentCaller, args: dict) -> dict:
    try:
        return _ok(await reports.accept(manager, caller, args))
    except reports.ReportRefused as exc:
        raise ToolError(str(exc)) from None


async def swarm_propose_naming(manager: Any, caller: AgentCaller, args: dict) -> dict:
    """
    Inputs: args ``family``, ``persona``, ``reason`` (text). Output: result ``{item_id}`` of the review card.
    """
    try:
        agent = await spawn.parent_agent(manager, caller)
        return _ok({"item_id": await project_agent.propose_naming(agent, args.get("family"), args.get("persona"), args.get("reason"))})
    except (spawn.SpawnRefused, project_agent.TurnOnError) as exc:
        raise ToolError(str(exc)) from None


async def swarm_suggest(manager: Any, caller: AgentCaller, args: dict) -> dict:
    try:
        return _ok(await suggest.suggest(manager, caller, args))
    except (spawn.SpawnRefused, suggest.SuggestRefused) as exc:
        raise ToolError(str(exc)) from None


async def swarm_remember(manager: Any, caller: AgentCaller, args: dict) -> dict:
    try:
        return _ok(await facts.remember(manager, caller, args))
    except facts.FactRefused as exc:
        raise ToolError(str(exc)) from None


async def swarm_ask(manager: Any, caller: AgentCaller, args: dict) -> dict:
    try:
        return _ok(await routing.ask(manager, caller, args))
    except routing.QuestionRefused as exc:
        raise ToolError(str(exc)) from None


async def swarm_answer(manager: Any, caller: AgentCaller, args: dict) -> dict:
    try:
        return _ok(await answers.answer(manager, caller, args))
    except routing.QuestionRefused as exc:
        raise ToolError(str(exc)) from None


async def swarm_pass(manager: Any, caller: AgentCaller, args: dict) -> dict:
    try:
        return _ok(await answers.pass_up(manager, caller, args))
    except routing.QuestionRefused as exc:
        raise ToolError(str(exc)) from None


async def swarm_promote(manager: Any, caller: AgentCaller, args: dict) -> dict:
    agent_id, decision = _agent_id(args), args.get("decision") or "promote"
    if decision not in ("promote", "teardown"):
        raise ToolError("decision must be promote or teardown")
    try:
        parent = await spawn.parent_agent(manager, caller)
        if decision == "teardown":
            return _ok(await promotion.teardown_candidate(manager.app.state, parent["id"], agent_id))
        return _ok(await promotion.promote(manager.app.state, parent["id"], agent_id, args.get("specialty")))
    except (spawn.SpawnRefused, promotion.PromotionRefused, body.BodyError) as exc:
        raise ToolError(str(exc)) from None


async def swarm_say(manager: Any, caller: AgentCaller, args: dict) -> dict:
    try:
        return _ok(await say.say(manager, caller, args))
    except say.SayRefused as exc:
        raise ToolError(str(exc)) from None


async def swarm_set_look(manager: Any, caller: AgentCaller, args: dict) -> dict:
    agent_id, fields, shown = _agent_id(args), {}, {}
    if "shape" in args:
        shape = args["shape"]
        if shape != "default" and shape not in get_args(LookShape):
            raise ToolError(f"shape must be one of {', '.join(get_args(LookShape))}, or \"default\"")
        fields["shape"], shown["shape"] = (None if shape == "default" else shape), shape
    if "background" in args:
        bg = args["background"]
        if bg != "none" and (type(bg) is not int or not 1 <= bg <= 8):
            raise ToolError("background must be a whole number from 1 to 8, or \"none\"")
        fields["tile_bg"], shown["background"] = (None if bg == "none" else bg), bg
    if not fields:
        raise ToolError("name a shape, a background, or both")
    what = ", ".join(f"{k} {v}" for k, v in shown.items())
    return await _park_look(manager, caller, "swarm_set_look", agent_id, fields, f"set Swarm agent {agent_id}'s {what}",
                            {"agent_id": agent_id, **shown})


async def _park_look(manager: Any, caller: AgentCaller, tool: str, agent_id: int, fields: dict, summary: str, answer: dict) -> dict:
    from src.core.mcp import write_tools

    async def go(_approved: bool) -> dict:
        try:
            await body.run_db(lambda c: store.update_agent(c, agent_id, **fields))
        except store.AgentNotFound:
            raise ToolError("no such agent") from None
        except (db.DatastoreUnreadableError, sqlite3.Error):
            raise ToolError("the Swarm datastore could not be read") from None
        return _ok(answer)

    return await write_tools.park(manager, caller, caller.current_session_id, caller.tmux_name, tool, summary, answer, go)


async def swarm_rename(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.core.mcp import write_tools

    agent_id = _agent_id(args)
    try:
        own_caller = await spawn.parent_agent(manager, caller)
    except spawn.SpawnRefused:
        own_caller = None
    try:
        target, name = await body.run_db(lambda c: rename.checked(c, agent_id, args.get("name")))
    except store.AgentNotFound:
        raise ToolError("no such agent") from None
    except rename.RenameRefused as exc:
        raise ToolError(str(exc)) from None
    except (db.DatastoreUnreadableError, sqlite3.Error):
        raise ToolError("the Swarm datastore could not be read") from None
    own = rename.is_own(own_caller, target)

    async def go(_approved: bool) -> dict:
        try:
            done = await rename.rename(agent_id, name)
        except store.AgentNotFound:
            raise ToolError("no such agent") from None
        except rename.RenameRefused as exc:
            raise ToolError(str(exc)) from None
        except (db.DatastoreUnreadableError, sqlite3.Error):
            raise ToolError("the Swarm datastore could not be read") from None
        return _ok({"agent_id": agent_id, "display_name": done["display_name"], "former_names": naming_rules.former_names(done)})

    whose = "" if own else " (not the caller's own agent: only on the owner's order)"
    return await write_tools.park(manager, caller, caller.current_session_id, caller.tmux_name, "swarm_rename",
                                  f"rename Swarm agent {agent_id} from {target['display_name']!r} to {name!r}{whose}",
                                  {"agent_id": agent_id, "name": name}, go, beast_eligible=own)


async def swarm_conflict(manager: Any, caller: AgentCaller, args: dict) -> dict:
    """The calling agent reports one collision it met (#1439): it counts toward ITS OWN project's merge-conflict throttle.

    Inputs: args ``kind`` (one of ``conflicts.KINDS``). Output: result ``{project_id, kind, recent, window_minutes, threshold,
    throttled, limit, lifts_at}``. Raises ToolError (not a Swarm agent, no project, a bad kind, the record could not be written).
    """
    try:
        agent = await spawn.parent_agent(manager, caller)
    except spawn.SpawnRefused as exc:
        raise ToolError(str(exc)) from None
    kind = args.get("kind")
    if kind not in conflicts.KINDS:
        raise ToolError(f"kind must be one of {', '.join(conflicts.KINDS)}")
    if agent.get("project_id") is None:
        raise ToolError("you belong to no project, so there is no throttle to count toward")
    try:
        return _ok(await asyncio.to_thread(conflicts.record, int(agent["project_id"]), kind))
    except OSError as exc:
        logger.warning("swarm_conflict_record_failed", agent_id=agent["id"], error_type=type(exc).__name__)
        raise ToolError("the conflict could not be recorded") from None


WRITE_TOOLS: frozenset = frozenset({"swarm_spawn", "swarm_report", "swarm_accept_report", "swarm_propose_naming",
                                  "swarm_suggest", "swarm_remember", "swarm_ask", "swarm_answer", "swarm_pass", "swarm_promote", "swarm_say",
                                  "swarm_rewind", "swarm_set_look", "swarm_rename", "swarm_conflict"})

_DETAIL = {"type": "boolean", "description": "full answer instead of the lean default"}

TOOLS: dict = {
    "swarm_roster": ("Every live Swarm agent (id, name, rank, state, project, company, session, activity) and the body caps. "
                     "detail true adds every field (look, host, persona, folder).", {"detail": _DETAIL}, [], swarm_roster),
    "swarm_agent": ("One Swarm agent in full: goal, children, open wake and its body when awake.",
                   {"agent_id": {"type": "integer", "minimum": 1}}, ["agent_id"], swarm_agent),
    "swarm_conversation": (
        "A Swarm agent's newest 20 conversation entries, oldest first (the owner's messages, the agent's, its cards). A bigger "
        "limit reaches older ones; detail true defaults to 50.",
        {"agent_id": {"type": "integer", "minimum": 1}, "detail": _DETAIL,
         "limit": {"type": "integer", "minimum": 1, "maximum": stream.MAX_LIMIT},
         "since": {"type": "string", "description": "an entry id: only later entries"}},
        ["agent_id"], swarm_conversation),
    "swarm_checkpoints": (
        "A Swarm agent's memory checkpoints: the commits of its project-scope memory folder, newest first (kind memory, promotion, "
        "flip_back or rewind). An empty list carries a reason (local memory is not in git).",
        {"agent_id": {"type": "integer", "minimum": 1}}, ["agent_id"], swarm_checkpoints),
    "swarm_conversations": (
        "A Swarm agent's earlier conversations, newest first, each with a measured transcript_present.",
        {"agent_id": {"type": "integer", "minimum": 1}}, ["agent_id"], swarm_conversations),
    "swarm_rewind": (
        "Restore a SLEEPING Swarm agent's memory folder to one of its checkpoints in a new commit (its next wake is fresh). "
        "Always waits for the owner's approval.",
        {"agent_id": {"type": "integer", "minimum": 1}, "sha": {"type": "string", "minLength": 7, "maxLength": 40}},
        ["agent_id", "sha"], swarm_rewind),
    "swarm_spawn": (
        "Start a feature or task agent under you (project agents only). Names: at most 25 characters, no feat/fix/tweak first "
        "word; a feature agent needs its specialty, and a live feature agent holding it gets the work instead (suggested_agent). "
        "The owner approves each spawn unless beast mode is armed. A busy computer refuses with \"system is pegged, try later\".",
        {"job": {"type": "string", "maxLength": spawn.MAX_JOB_CHARS, "description": "one plain line: the work"},
         "goal": {"type": "string", "maxLength": brief.MAX_GOAL_CHARS},
         "task_type": {"type": "string", "description": "a slug naming the kind of task"},
         "rank": {"type": "string", "enum": list(spawn.CHILD_RANKS)},
         "effort": {"type": "string", "enum": list(effort_floor.ALLOWED_EFFORTS),
                    "description": "default medium; high and xhigh need effort_reason; low and max are not allowed"},
         "effort_reason": {"type": "string", "description": "a written reason, required for high and xhigh"},
         "persona": {"type": "string"},
         "name": {"type": "string", "maxLength": spawn.MAX_NAME_CHARS,
                  "description": "the display name, at most 25 characters, never starting with feat/fix/tweak: a task agent's general "
                                 "task (\"fixing node colors\"), a feature agent's specialty (\"Icon Design\"); default: the specialty or job"},
         "specialty": {"type": "string", "maxLength": spawn.MAX_NAME_CHARS,
                       "description": "required for a feature agent: the domain it owns (\"Security Analyst\"); a live feature agent "
                                      "holding it gets the work instead (suggested_agent)"},
         "spawn_reason": {"type": "string", "maxLength": spawn.MAX_SPAWN_REASON_CHARS,
                          "description": "why a new agent although a live feature agent holds this specialty"},
         "launch_profile": {"type": "string", "description": "a launch profile id from launch_profiles_list"},
         "harness": {"type": "string", "enum": list(spawn.HARNESSES)},
         "machine": {"type": "string", "description": "run it on this paired computer (label from pack_machines); default: placed by the Pack"},
         "card": {"type": "integer", "minimum": 1, "description": "a waiting card to deal to the new agent; without it a card is made from the goal"}},
        ["job", "goal", "task_type", "rank"], swarm_spawn),    "swarm_report": (
        "Report your work done to your parent agent: a done card in your thread and a line in its thread. Your parent "
        "then accepts it (a task agent is torn down) or sends it back with a note. One report waits at a time.",
        {"summary": {"type": "string", "maxLength": reports.MAX_REPORT_CHARS, "description": "what was done, in plain words"},
         "done_items": {"type": "array", "items": {"type": "string"}, "maxItems": reports.MAX_DONE_ITEMS,
                        "description": "the goal's done-means items, each one finished"},
         "how_to_validate": {"type": "string", "maxLength": 4000, "description": "required when you hold a card: steps the owner can run to check it"},
         "card": {"type": "integer", "minimum": 1, "description": "the card you are reporting, only when you hold more than one"}},
        ["summary"], swarm_report),
    "swarm_accept_report": (
        "Accept or reject a report from one of your own child agents. Accepting a task agent's report tears it down "
        "(the transcript stays in the archive), unless its task type reached the project's promotion threshold: then it "
        "sleeps for swarm_promote. A feature agent sleeps instead. A report left undecided past the close-out window is "
        "accepted for you (Swarm setting closeout_default).",
        {"report_id": {"type": "integer", "minimum": 1}, "decision": {"type": "string", "enum": list(reports.DECISIONS)},
         "note": {"type": "string", "maxLength": reports.MAX_NOTE_CHARS, "description": "why, handed to the child on a reject"}},
        ["report_id", "decision"], swarm_accept_report),
    "swarm_propose_naming": (
        "Project agents only: propose the naming family for your agents' persona names and your own persona name. The "
        "owner approves it as a card; until then spawn with plain job names.",
        {"family": {"type": "string", "maxLength": project_agent.MAX_FAMILY_CHARS, "description": "the theme, e.g. Norse gods"},
         "persona": {"type": "string", "maxLength": project_agent.MAX_PERSONA_CHARS, "description": "your own name from that theme"},
         "reason": {"type": "string", "maxLength": project_agent.MAX_REASON_CHARS}},
        ["family", "persona", "reason"], swarm_propose_naming),
    "swarm_suggest": (
        "Suggest a new company (SysOp only) or a new project for your own company (company agents only). The owner approves it "
        "as a card in SysOp's thread; nothing is created before then. name is a folder name; for a project the company already "
        "has without an agent, suggest it by its name to ask for its agent.",
        {"kind": {"type": "string", "enum": list(suggest.KINDS)},
         "name": {"type": "string", "maxLength": suggest.MAX_NAME_CHARS},
         "reason": {"type": "string", "maxLength": suggest.MAX_REASON_CHARS},
         "company_id": {"type": "integer", "minimum": 1, "description": "a project suggestion's own company; may be left out"}},
        ["kind", "name", "reason"], swarm_suggest),
    "swarm_remember": (
        "Write one fact into your own memory: text, or learning_id (a learning item in your inbox, copied verbatim), or "
        "owner_message_ref (huddle:msg:<id> of an owner message in YOUR thread, stored as an owner fact). A fact that clashes "
        "with one the owner taught is held until the owner decides. scope: craft (any project) or project (this repo only).",
        {"title": {"type": "string", "maxLength": facts.MAX_TITLE_CHARS},
         "scope": {"type": "string", "enum": list(facts.memory.FACT_SCOPES)},
         "text": {"type": "string", "maxLength": facts.MAX_FACT_CHARS},
         "learning_id": {"type": "integer", "minimum": 1},
         "owner_message_ref": {"type": "string", "pattern": "^huddle:msg:[0-9]+$"},
         "push_up": {"type": "boolean", "description": "also queue this as a discovery for your parent"}},
        ["title", "scope"], swarm_remember),    "swarm_ask": (
        "Ask what you cannot answer from memory. It goes up your chain (project, company, SysOp agent), each asked in turn; "
        "if all pass, the owner gets it. The answer arrives later as text in your session. An open question covering yours is joined. "
        "The owner reads summary first (one sentence, no code, paths or line numbers, else refused); question holds every detail.",
        {"question": {"type": "string", "maxLength": routing.MAX_QUESTION_CHARS,
                      "description": "the full question with every detail, verbatim: the owner reads it under full details"},
         "summary": {"type": "string", "maxLength": routing.MAX_SUMMARY_CHARS,
                     "description": "one short plain-English sentence the owner can answer without reading code: no file names, "
                                    "line numbers or code, and say what the choice changes for the owner"},
         "task": {"type": "string", "maxLength": routing.MAX_TASK_CHARS,
                  "description": "optional: what you are working on, in plain words (default: the title of the card you hold, "
                                 "else your job)"}},
        ["question", "summary"], swarm_ask),
    "swarm_answer": (
        "Answer a question that was routed to you. fact_ids are YOUR stored facts you relied on: the server keeps only "
        "live facts of yours and writes the receipt itself. No stored fact means your answer is marked as your judgment. "
        "It reaches the asker as your words, never the owner's, even when it repeats what the owner told you.",
        {"question_id": {"type": "integer", "minimum": 1},
         "text": {"type": "string", "maxLength": answers.MAX_ANSWER_CHARS},
         "fact_ids": {"type": "array", "items": {"type": "string"}, "maxItems": receipts.MAX_FACT_IDS}},
        ["question_id", "text"], swarm_answer),
    "swarm_pass": (
        "Pass a question that was routed to you when you cannot answer it well; it goes to the next tier or the owner.",
        {"question_id": {"type": "integer", "minimum": 1},
         "reason": {"type": "string", "maxLength": answers.MAX_REASON_CHARS}}, ["question_id"], swarm_pass),
    "swarm_promote": (
        "Project agents only: promote one of your candidate task agents (the desk names them: a task type accepted enough times) "
        "to a feature agent named by its specialty (required). Its memory becomes project memory in the repo, and the next task of "
        "that type goes to it. decision teardown declines and erases the candidate as an accepted report would have.",
        {"agent_id": {"type": "integer", "minimum": 1},
         "specialty": {"type": "string", "maxLength": naming_rules.MAX_NAME_CHARS,
                       "description": "required to promote: the domain it will own, its new name (\"Style Guide\"); at most 25 characters"},
         "decision": {"type": "string", "enum": ["promote", "teardown"], "description": "promote (the default) or teardown"}},
        ["agent_id"], swarm_promote),
    "swarm_set_look": (
        "Set a Swarm agent's own shape (one of the ten Swarm look shapes, or \"default\" for its tier's) and tile background "
        "(1 to 8, or \"none\"); name either or both. The owner approves each call.",
        {"agent_id": {"type": "integer", "minimum": 1},
         "shape": {"type": "string", "enum": [*get_args(LookShape), "default"]},
         "background": {"oneOf": [{"type": "integer", "minimum": 1, "maximum": 8}, {"type": "string", "enum": ["none"]}]}},
        ["agent_id"], swarm_set_look),
    "swarm_rename": (
        "Rename a Swarm agent's display name; its id, slug, memory, cards and thread stay and its old name still resolves. Rules: at "
        "most 25 characters, no feat/fix/tweak first word, not another live agent's name in the project. Rename yourself or your own "
        "children; any other agent only on the owner's order. The owner approves each call.",
        {"agent_id": {"type": "integer", "minimum": 1},
         "name": {"type": "string", "minLength": 1, "maxLength": naming_rules.MAX_NAME_CHARS}},
        ["agent_id", "name"], swarm_rename),
    "swarm_conflict": (
        "Report a collision you met: a rebase or merge that stopped on a conflict, a push the remote rejected, or a wait on the "
        "merge lock. It counts toward your own project's throttle: 3 reports in 30 minutes cap the project at 3 live agents until "
        "30 minutes pass with none.",
        {"kind": {"type": "string", "enum": list(conflicts.KINDS)}}, ["kind"], swarm_conflict),
    "swarm_say": (
        "Tell the owner something between turns, unprompted (a status worth pushing): the text is posted as your own message "
        "in your thread. Never use it to answer an owner message: your final answer of a turn the owner started is posted "
        "to your thread for you, word for word, and a swarm_say made inside that turn is held.",
        {"text": {"type": "string", "minLength": 1, "maxLength": say.MAX_SAY_CHARS}}, ["text"], swarm_say),
}

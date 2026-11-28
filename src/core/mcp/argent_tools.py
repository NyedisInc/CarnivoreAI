
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra
from src.core.mcp import session_target
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok


def _status(call: ra.Call) -> Any:
    return call.route()


async def argent_switch_off(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.argent.status import ArgentSettingsPatch, put_settings

    if args:
        raise ToolError("argent_switch_off takes no arguments; it can only turn the tether off")
    return _ok(await put_settings(ArgentSettingsPatch(enabled=False)))


async def argent_story_declare(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.core.argent import declare, subagent_join

    if caller.from_token or caller.proxied_agent_id:
        raise ToolError("argent_story_declare declares the work of the calling session itself: only a session running on this computer may call it")
    unknown = sorted(set(args) - {"work_item_id"})
    item = args.get("work_item_id")
    if unknown or not isinstance(item, str) or not item.strip():
        raise ToolError("argent_story_declare takes exactly one argument, work_item_id (the id of the work item you are on)")
    found = await subagent_join.agent_for_pane_call(manager, caller.current_session_id, caller.tmux_name,
                                                    tool_name=f"mcp__carnivore__{DECLARE_TOOL}", tool_input=args)
    try:
        done = await declare.declare(caller.tmux_name, item, "mcp-self", found.sub_agent_id)
    except declare.DeclareError as exc:
        raise ToolError(f"{exc.code}: {exc}") from None
    return _ok({**done, "joined": found.how})


async def _work_items(call: ra.Call) -> Any:
    return await call.route(kind=call.args.get("kind"), parent_id=call.args.get("parent_id"), state=call.args.get("state"), q=call.args.get("q"))


async def _work_item_create(call: ra.Call) -> Any:
    from src.api.argent.work_items import WorkItemCreate

    return await call.route(WorkItemCreate(**call.args))


async def _work_item_close(call: ra.Call) -> Any:
    from src.api.argent.close import CloseBody

    return await call.route(call.args.get("item_id"), CloseBody(reason=call.args.get("reason", "")))


async def _retag(call: ra.Call) -> Any:
    from src.api.argent.close import RetagBody

    return await call.route(call.request, RetagBody(**call.args))


def _cost(call: ra.Call) -> Any:
    return call.route()


def _holds(call: ra.Call) -> Any:
    return call.route()


def _budget_requests_list(call: ra.Call) -> Any:
    return call.route()


async def _budget_request(call: ra.Call) -> Any:
    from src.api.argent.cost import BudgetRequest

    return await call.route(BudgetRequest(**call.args))


def _writeback_review(call: ra.Call) -> Any:
    return call.route()


def _rollout(call: ra.Call) -> Any:
    return call.route()


DECLARE_TOOL = "argent_story_declare"

SPECS = (
    ra.RouteTool(
        name="argent_context_get", route="src.api.argent.context:get_context", gate=ra.READ, reach=session_target.LIVE,
        description="Which argent work item a live session and each of its sub-agents are on: per agent the declared item and the item it effectively "
                    "serves (an undeclared sub-agent inherits the root agent's), when and from which source, plus how many declarations still await "
                    "argent. Empty with the feature off or no login. Read only.",
        invoke=lambda call: call.route(call.request, call.session_id), example={},
    ),
    ra.RouteTool(
        name="argent_status", route="src.api.argent.status:get_status", gate=ra.READ,
        description="Read the argent feature: whether it is on (feature_on), the tether switch and saved addresses (settings), the gateway "
                    "state (up, down, unsupported, cap_too_low, login_expired, unknown), why the switch cannot turn on (refusal), health facts "
                    "and the login state. No token is ever shown. Agents can turn the tether off (argent_switch_off), never on. Read only.",
        invoke=_status, example={},
    ),
    ra.RouteTool(
        name="argent_rollout_status", route="src.api.argent.rollout:get_rollout", gate=ra.READ,
        description="The argent gateway rollout: state (none, running, paused, cancelled, done, off), direction (on or off), counts per row state and per reason, "
                    "and every row (tmux_name, state, reason). Starting or cancelling it is the owner's, in the app. Read only.",
        invoke=_rollout, example={},
    ),
    ra.RouteTool(
        name="argent_cost_get", route="src.api.argent.cost:get_cost", gate=ra.READ,
        description="Argent cost and budgets as last polled: per local session (by row id) its items and cost; per item its name, cost, budget "
                    "(state ok, warn or paused, spent_micros, cap_micros, owner_name, resets_at) and whether prompts are held. Money is micros "
                    "of USD. null means not measured, never zero. Read only.",
        invoke=_cost, example={},
    ),
    ra.RouteTool(
        name="argent_holds_list", route="src.api.argent.holds_routes:list_holds", gate=ra.READ,
        description="The argent budget holds: each work item at its budget with the session row ids whose next prompt is held. Only the budget owner lifts a hold, in argent "
                    "or in the app; no tool does. Read only.",
        invoke=_holds, example={},
    ),
    ra.RouteTool(
        name="argent_budget_request", route="src.api.argent.cost:request_budget", gate=ra.ACT,
        description="Ask the budget owner of an argent work item for more budget: item_id, amount_micros (extra added to your allotment on approval, not a new cap) and reason (1 to 500 characters). "
                    "Argent's owner approves or denies it in argent; a second ask while one waits is refused (budget_request_pending), and 501 budget_request_unavailable means "
                    "argent does not take the ask yet. Waits for the owner.",
        properties={"item_id": {"type": "string", "minLength": 1, "maxLength": 200}, "amount_micros": {"type": "integer", "minimum": 1, "description": "the EXTRA amount added to your current allotment on approval, not a new cap, in whole millionths of a dollar, above zero"},
                    "reason": {"type": "string", "minLength": 1, "maxLength": 500}},
        required=("item_id", "amount_micros", "reason"), invoke=_budget_request,
        summary=lambda args, _t: f"ask for {args.get('amount_micros')} micros more argent budget on {str(args.get('item_id'))[:80]}",
        example={"item_id": "wi_fixture", "amount_micros": 5000000, "reason": "fixture"},
    ),
    ra.RouteTool(
        name="argent_budget_requests_list", route="src.api.argent.cost:list_budget_requests", gate=ra.READ,
        description="The asks for more argent budget this computer filed: id, item_id, requested_micros, approved_micros, state (pending, approved, denied, expired), decision_reason, "
                    "times. Read from the local record, no call to argent. Read only.",
        invoke=_budget_requests_list, example={},
    ),
    ra.RouteTool(
        name="argent_work_item_close", route="src.api.argent.close:close_work_item", gate=ra.ACT,
        description="Close an argent work item (item_id from argent_work_items_list, optional reason, at most 200 characters): argent moves it to done and a closing comment "
                    "is queued for the work item. Waits for the owner.",
        properties={"item_id": {"type": "string", "minLength": 1, "maxLength": 200}, "reason": {"type": "string", "maxLength": 200}},
        required=("item_id",), invoke=_work_item_close,
        summary=lambda args, _t: f"close argent work item {str(args.get('item_id'))[:80]}",
        example={"item_id": "wi_fixture"},
    ),
    ra.RouteTool(
        name="argent_retag", route="src.api.argent.close:retag", gate=ra.ACT,
        description="Move the spend of one of the owner's local sessions in a time window (31 days at most, not in the future) to another argent work item. Own spend only; "
                    "the reason (3 to 200 characters) is kept in argent's change log and history is never rewritten. since and until are ISO 8601 with a time zone. "
                    "Waits for the owner.",
        properties={"session_id": {"type": "string", "minLength": 1, "maxLength": 200}, "since": {"type": "string", "minLength": 10, "maxLength": 40},
                    "until": {"type": "string", "minLength": 10, "maxLength": 40}, "work_item_id": {"type": "string", "minLength": 1, "maxLength": 200},
                    "reason": {"type": "string", "minLength": 3, "maxLength": 200}},
        required=("session_id", "since", "until", "work_item_id", "reason"), invoke=_retag,
        summary=lambda args, _t: f"re-tag argent spend of {str(args.get('session_id'))[:60]} to {str(args.get('work_item_id'))[:60]}",
        example={"session_id": "ses_fixture", "since": "2026-11-01T00:00:00Z", "until": "2026-11-02T00:00:00Z", "work_item_id": "wi_fixture", "reason": "fixture"},
    ),
    ra.RouteTool(
        name="argent_writeback_review_list", route="src.api.argent.writeback:get_review", gate=ra.READ,
        description="The argent write-back comments waiting for the owner's review (held while Beast Mode is off): id, work item, body, session name, number of commits. "
                    "Approving, editing and discarding them is the owner's, in the app; no tool does. Read only.",
        invoke=_writeback_review, example={},
    ),
    ra.RouteTool(
        name="argent_work_items_list", route="src.api.argent.work_items:list_work_items", gate=ra.READ,
        description="The argent projects, features and stories the owner can see (a cache Carnivore pulls): id, kind, parent_id, title, status, "
                    "external_key, sprint_state. Filters: kind, parent_id, state (sprint state: active, future, closed or none), q (title text). state in the answer is off, "
                    "pending, ok, login_required, login_expired or unavailable. Read only.",
        properties={"kind": {"type": "string", "enum": ["project", "feature", "story"]}, "parent_id": {"type": "string", "maxLength": 200},
                    "state": {"type": "string", "maxLength": 100}, "q": {"type": "string", "maxLength": 200}},
        invoke=_work_items, example={},
    ),
    ra.RouteTool(
        name="argent_work_item_create", route="src.api.argent.work_items:create_work_item", gate=ra.ACT,
        description="Create an argent project, feature or story (a feature or story needs its parent_id). Argent joins a near-identical title to the "
                    "existing item (the answer has created: false); a similar one that is not identical comes back as a conflict with candidates, and nothing is created. "
                    "Waits for the owner.",
        properties={"kind": {"type": "string", "enum": ["project", "feature", "story"]}, "parent_id": {"type": "string", "maxLength": 200},
                    "title": {"type": "string", "minLength": 1, "maxLength": 200}},
        required=("kind", "title"), invoke=_work_item_create,
        summary=lambda args, _t: f"create argent {str(args.get('kind'))[:20]}: {str(args.get('title'))[:80]}",
        example={"kind": "project", "title": "fixture"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
WRITE_TOOLS["argent_switch_off"] = (
    "Turn the argent tether OFF (new sessions launch directly again; running sessions keep their own keys until restarted). Runs at once. "
    "No tool can turn it on: only the owner does, in the app.",
    {}, [], argent_switch_off,
)
WRITE_TOOLS[DECLARE_TOOL] = (
    "Declare the argent work item (an id from argent_work_items_list) you are on, so your spend is tagged to it. Self only, sub-agents included; never changes a "
    "budget or owner. Runs at once. Starting a sub-agent: put `argent-story: <item id>` first in its prompt and tell it to call this tool.",
    {"work_item_id": {"type": "string", "minLength": 1, "maxLength": 200}}, ["work_item_id"], argent_story_declare,
)

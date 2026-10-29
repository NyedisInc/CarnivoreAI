
from __future__ import annotations

import re
from typing import Any

from src.core.mcp import route_adapters as ra
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok


SPECS = (
    ra.RouteTool(
        name="messaging_providers_list", route="src.api.messaging_routes:list_providers", gate=ra.READ,
        description="Messaging providers (the owner's iMessage bridge and the like): name, capabilities and stream "
                    "state. Never a URL, token or handle.",
        invoke=lambda call: call.route(call.request),
    ),
)

_READS, _WRITES, UNGATED_WRITES = ra.tables(SPECS)


async def _park_binding(manager: Any, caller: AgentCaller, action: str, summary: str, args: dict,
                        target_id: str, target_tmux: str, route: Any) -> dict:
    import hashlib
    import json

    from fastapi import HTTPException

    from src.core.mcp.write_tools import _as_result, _detail, park

    async def run(_approved: bool) -> dict:
        try:
            return _ok(jsonable(await route()))
        except HTTPException as exc:
            raise ToolError(_detail(exc)) from exc

    key = hashlib.sha256(json.dumps([action, args], sort_keys=True, default=str).encode()).hexdigest()
    return await _as_result(park(manager, caller, target_id, target_tmux, action, summary, args, run, dedupe_key=key,
                                 beast_eligible=action != "messaging_binding_delete"))


REF_CHARS = 16
_HANDLE_LIKE = re.compile(r"@|\d[\d\s().+-]{5,}\d")
UNNAMED = "(unnamed conversation)"


def safe_label(label: str) -> str:
    label = (label or "").strip()
    return UNNAMED if not label or _HANDLE_LIKE.search(label) else label


async def _route(call: Any) -> Any:
    from fastapi import HTTPException

    from src.core.mcp.write_tools import _detail

    try:
        return jsonable(await call)
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc


async def _provider_of(manager: Any, name: Any) -> dict:
    from src.api.messaging_routes import list_providers

    providers = (await _route(list_providers(ra.route_request(manager))))["providers"]
    if name is None and len(providers) == 1:
        return providers[0]
    found = [p for p in providers if name in (p["id"], p["name"])]
    if len(found) != 1:
        raise ToolError("name the provider (an id or name from messaging_providers_list)" if name is None
                        else f"no messaging provider {name!r}")
    return found[0]


async def _live_routable(manager: Any, provider_id: str) -> list[dict]:
    from src.api.messaging_routes import provider_conversations, runtime_of
    from src.core.messaging.secrets import match_of

    request = ra.route_request(manager)
    state = runtime_of(request).providers.get(provider_id)
    if state is None:
        raise ToolError("provider_not_loaded")
    entries = (await _route(provider_conversations(request, provider_id)))["conversations"]
    out = []
    for e in entries:
        if e["routable"]:
            match = match_of(state.secrets.match_key, e["conversation"])
            out.append({"handle": e["conversation"], "match": match, "ref": match[:REF_CHARS],
                        "label": safe_label(e["label"]), "people": e["participants"]})
    return out


async def _registered(manager: Any, provider_id: str) -> dict[str, dict]:
    import asyncio

    from src.api.messaging_routes import list_conversations
    from src.core.messaging import store

    rows = (await _route(list_conversations(ra.route_request(manager), provider_id)))["conversations"]
    out = {}
    for row in rows:
        full = await asyncio.to_thread(store.get_conversation, row["id"])
        if full:
            out[full["match_key"]] = {"id": row["id"], "label": row["label"]}
    return out


async def messaging_conversations_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    extra = sorted(set(args) - {"provider"})
    if extra:
        raise ToolError(f"messaging_conversations_list does not take {', '.join(extra)}; it takes provider")
    provider = await _provider_of(manager, args.get("provider"))
    live = await _live_routable(manager, provider["id"])
    known = await _registered(manager, provider["id"])
    return _ok({"provider": {"id": provider["id"], "name": provider["name"]},
                "available": [{"ref": c["ref"], "name": c["label"], "people": c["people"],
                               "registered": (known.get(c["match"]) or {}).get("id")} for c in live],
                "registered": [{"id": v["id"], "name": v["label"]} for v in known.values()]})


async def messaging_conversation_add(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.messaging_routes import ConversationCreate, create_conversation

    extra = sorted(set(args) - {"provider", "conversation", "label"})
    if extra or not isinstance(args.get("conversation"), str) or not isinstance(args.get("label", ""), str):
        raise ToolError("messaging_conversation_add takes provider, conversation (a ref) and optional label")
    provider = await _provider_of(manager, args.get("provider"))

    async def pick() -> dict:
        found = [c for c in await _live_routable(manager, provider["id"]) if c["ref"] == args["conversation"]]
        if len(found) != 1:
            raise ToolError("not_routable: that conversation is not listed as routable by the provider now; "
                            "call messaging_conversations_list again")
        return found[0]

    chosen = await pick()
    label = (args.get("label") or "").strip() or chosen["label"]
    if label == UNNAMED:
        raise ToolError("that conversation has no display name; pass a label")
    summary = f"add the messaging conversation '{chosen['label']}' on {provider['name']} to Carnivore as '{label}'"
    request = ra.route_request(manager)

    async def register() -> Any:
        again = await pick()
        return await create_conversation(request, ConversationCreate(provider_id=provider["id"],
                                                                     conversation=again["handle"], label=label))
    return await _park_binding(manager, caller, "messaging_conversation_add", summary,
                               {"provider": provider["id"], "conversation": args["conversation"], "label": label},
                               "", "", register)


def jsonable(value: Any) -> Any:
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(value)


async def messaging_binding_create(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.messaging_routes import BindingCreate, create_binding
    from src.core.mcp import session_target

    extra = sorted(set(args) - {"target", "conversation", "direction", "default"})
    if extra or not all(isinstance(args.get(k), str) for k in ("target", "conversation", "direction")):
        raise ToolError("messaging_binding_create takes target, conversation, direction and optional default")
    resolver = session_target.TargetResolver(manager)
    target = await resolver.resolve(args, reach=session_target.STORED, tool="messaging_binding_create")
    uuid = await resolver.uuid_of(target)
    try:
        body = BindingCreate(conversation_id=args["conversation"], session_uuid=uuid, direction=args["direction"],
                             default=bool(args.get("default", False)))
    except ValueError as exc:
        raise ToolError(f"messaging_binding_create: invalid arguments: {' '.join(str(exc).split())[:300]}") from exc
    tmux = (target.info.tmux_session if target.live else target.tmux_name) or ""
    summary = f"bind {tmux or uuid} to messaging conversation {args['conversation']} ({args['direction']})"
    request = ra.route_request(manager)
    return await _park_binding(manager, caller, "messaging_binding_create", summary, args,
                               target.info.session.id if target.live else uuid, tmux,
                               lambda: create_binding(request, body))


async def messaging_binding_delete(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.messaging_routes import delete_binding

    if sorted(args) != ["binding"] or not isinstance(args.get("binding"), str):
        raise ToolError("messaging_binding_delete takes binding (an id from messaging_bindings_list)")
    request = ra.route_request(manager)
    return await _park_binding(manager, caller, "messaging_binding_delete", f"remove messaging binding {args['binding']}",
                               args, "", "", lambda: delete_binding(request, args["binding"]))


async def messaging_send(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from fastapi import HTTPException

    from src.api.messaging_agent_routes import SendBody, send_for_caller
    from src.core.mcp.write_tools import _detail

    extra = sorted(set(args) - {"text", "conversation"})
    if extra:
        raise ToolError(f"messaging_send does not take {', '.join(extra)}; it takes text, conversation")
    if not isinstance(args.get("text"), str) or not args["text"].strip():
        raise ToolError("messaging_send needs text")
    if caller.external:
        raise ToolError("messaging_send is for a running pane, not an external token: it sends as a bound session")
    try:
        body = SendBody(text=args["text"], conversation_id=args.get("conversation"))
        return _ok(await send_for_caller(ra.route_request(manager), caller, body))
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc
    except ValueError as exc:
        raise ToolError(f"messaging_send: invalid arguments: {' '.join(str(exc).split())[:300]}") from exc


async def messaging_bindings_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.messaging_routes import list_bindings
    from src.core.mcp import session_target

    extra = sorted(set(args) - {"target"})
    if extra:
        raise ToolError(f"messaging_bindings_list does not take {', '.join(extra)}; it takes target")
    resolver = session_target.TargetResolver(manager)
    if args.get("target"):
        target = await resolver.resolve(args, reach=session_target.STORED, tool="messaging_bindings_list")
    elif caller.external:
        raise ToolError("messaging_bindings_list needs target from an external token")
    else:
        target = await resolver.resolve({"target": caller.tmux_name}, reach=session_target.LIVE,
                                        tool="messaging_bindings_list")
    uuid = await resolver.uuid_of(target)
    from fastapi import HTTPException

    from src.core.mcp.write_tools import _detail

    try:
        return _ok(await list_bindings(ra.route_request(manager), session_uuid=uuid))
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc


READ_TOOLS = {
    **_READS,
    "messaging_conversations_list": (
        "A provider's routable conversations (name and ref, live) and those already registered (Carnivore id). "
        "Setup flow: this, messaging_conversation_add, messaging_binding_create, messaging_send. Never a handle.",
        {"provider": {"type": "string", "description": "id or name; omit with one provider"}}, [],
        messaging_conversations_list),
    "messaging_bindings_list": (
        "Your session's messaging bindings (or a named session's, with target): conversation, direction, default and "
        "held count. Never a secret.",
        {"target": {"type": "string", "description": "a session id or tmux name; omit for your own"}}, [],
        messaging_bindings_list),
}
WRITE_TOOLS = {
    **_WRITES,
    "messaging_conversation_add": (
        "Register a conversation (ref from messaging_conversations_list) so it can be bound. Asks the owner unless "
        "Beast Mode is armed; re-checked routable at approval.",
        {"provider": {"type": "string"}, "conversation": {"type": "string", "description": "a ref"},
         "label": {"type": "string"}}, ["conversation"], messaging_conversation_add),
    "messaging_binding_create": (
        "Bind a session to a messaging conversation (direction in, out or both). Asks the owner unless "
        "Beast Mode is armed. Conversation id: from messaging_conversation_add.",
        {"target": {"type": "string"}, "conversation": {"type": "string"},
         "direction": {"type": "string", "enum": ["in", "out", "both"]}, "default": {"type": "boolean"}},
        ["target", "conversation", "direction"], messaging_binding_create),
    "messaging_binding_delete": (
        "Remove one messaging binding (id from messaging_bindings_list). Always waits for the owner's approval, "
        "whatever Beast Mode says.",
        {"binding": {"type": "string"}}, ["binding"], messaging_binding_delete),
    "messaging_send": (
        "Text the owner as your session through a messaging conversation bound to it (out or both). Runs at once: the "
        "binding is the owner's approval. Text only, 2000 characters at most; secrets are starred before sending.",
        {"text": {"type": "string"}, "conversation": {"type": "string", "description": "needed only with several"}},
        ["text"], messaging_send),
}

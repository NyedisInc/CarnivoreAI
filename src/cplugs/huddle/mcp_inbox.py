
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.cplugs.huddle import inbox, inbox_filing, own_list, rules, service
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError

Handler = Callable[[CplugContext, AgentCaller, dict], Awaitable[Any]]
Runner = Callable[[Callable[[], Any]], Awaitable[Any]]

FILE_ARGS = frozenset({"inbox_id", "items", own_list.FIELD})
LIST_ARGS = frozenset({"list"})


def _entry_id(args: dict) -> int:
    value = args.get("inbox_id")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolError("inbox_id is required: the entry id from the 'huddle inbox:' line or task_manager_entries_list")
    return value


async def inbox_list(ctx: CplugContext, args: dict, *, run: Runner, list_key: Optional[str]) -> Dict[str, Any]:
    unknown = sorted(set(args) - LIST_ARGS)
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    return {"entries": await run(lambda: InboxStore(service.store(ctx)).open_entries(list_key))}


async def inbox_file(ctx: CplugContext, caller: AgentCaller, args: dict, *, run: Runner, add: Handler, update: Handler, ask: Handler) -> Dict[str, Any]:
    unknown = sorted(set(args) - FILE_ARGS)
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    entry_id = _entry_id(args)
    specs = await run(lambda: inbox_filing.parse_specs(args.get("items")))
    store = InboxStore(service.store(ctx))
    entry = await run(lambda: store.get(entry_id))
    attached = await run(lambda: store.adopt_promoted(entry_id, service.store(ctx)._clock()))
    if attached:
        raise ToolError(f"inbox entry {entry_id} is already filed as item(s) {attached} (made when nobody filed it); update those instead of filing again")
    previous = await run(lambda: store.claim(entry_id, inbox.FILED, service.store(ctx)._clock()))
    carry = {own_list.FIELD: args[own_list.FIELD]} if own_list.FIELD in args else {}
    done: List[Dict[str, Any]] = []
    try:
        for spec in specs:
            done.append(await _file_one(ctx, caller, entry, spec, carry, run=run, add=add, update=update, ask=ask, store=store))
    except (ToolError, rules.TaskManagerError) as exc:
        ids = (await run(lambda: store.get(entry_id)))["item_ids"]
        if not ids:
            await run(lambda: store.release(entry_id, previous))
            raise
        raise ToolError(f"made item(s) {ids} from inbox entry {entry_id} ({len(done)} of {len(specs)} finished), then: {exc}") from exc
    return {"inbox_id": entry_id, "status": inbox.FILED, "items": done}


async def _file_one(ctx: CplugContext, caller: AgentCaller, entry: Dict[str, Any], spec: inbox_filing.ItemSpec, carry: dict, *,
                    run: Runner, add: Handler, update: Handler, ask: Handler, store: InboxStore) -> Dict[str, Any]:
    fields: Dict[str, Any] = {"list": entry["list"], "text": spec.text, "title": spec.title, **carry}
    if spec.group is not None:
        fields["group"] = spec.group
    if spec.perceived_ask is not None:
        fields["perceived_ask"] = spec.perceived_ask
    if spec.state == inbox_filing.QUESTION and spec.ask is None:
        fields["kind"] = rules.QUESTION
    added = await add(ctx, caller, fields)
    item_id = added["id"]
    await run(lambda: store.link_item(entry["id"], item_id))
    if spec.state in (inbox_filing.TODO, inbox_filing.WORKING):
        await update(ctx, caller, {"item": item_id, "state": spec.state})
    if spec.ask is not None:
        await ask(ctx, caller, {"item": item_id, **spec.ask})
    return {"item_id": item_id, "title": spec.title, "state": spec.state}

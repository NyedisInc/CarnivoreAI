
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from src.cplugs.huddle import inbox, perceived_ask, rules, service, title as titles
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.huddle.rules import TaskManagerInvalid
from src.cplugs.sdk import CplugContext

OPEN, TODO, WORKING, QUESTION = rules.OPEN, rules.TODO, "working", rules.QUESTION
STATES = (OPEN, TODO, WORKING, QUESTION)
OWNER_STATES = (OPEN, TODO)
SPEC_KEYS = frozenset({"title", "text", "group", "state", "ask", perceived_ask.FIELD})


@dataclass(frozen=True)
class ItemSpec:

    title: str
    text: str
    state: str = OPEN
    group: Optional[object] = None
    ask: Optional[Dict[str, Any]] = None
    perceived_ask: Optional[str] = None


def parse_specs(raw: object, *, allowed_states: Sequence[str] = STATES) -> List[ItemSpec]:
    if not isinstance(raw, list) or not raw:
        raise TaskManagerInvalid("items is required: a non-empty list of {title, text, group?, state?, ask?, perceived_ask?}")
    if len(raw) > inbox.MAX_FILED_ITEMS:
        raise TaskManagerInvalid(f"at most {inbox.MAX_FILED_ITEMS} items per entry (got {len(raw)})")
    specs: List[ItemSpec] = []
    for at, one in enumerate(raw, start=1):
        if not isinstance(one, dict):
            raise TaskManagerInvalid(f"item {at}: each item is an object {{title, text, group?, state?, ask?, perceived_ask?}}")
        unknown = sorted(set(one) - SPEC_KEYS)
        if unknown:
            raise TaskManagerInvalid(f"item {at}: unknown field(s) {', '.join(unknown)}")
        state = rules.canonical_state(one.get("state", OPEN))
        if state not in allowed_states:
            raise TaskManagerInvalid(f"item {at}: state must be one of {', '.join(allowed_states)}")
        ask = one.get("ask")
        if ask is not None and (not isinstance(ask, dict) or "context" not in ask and "questions" not in ask):
            raise TaskManagerInvalid(f"item {at}: ask is {{context?, questions?}}")
        title = rules.clean_text(one.get("title"), f"item {at} title", titles.MAX_TITLE)
        text = rules.clean_text(one.get("text"), f"item {at} text", rules.MAX_TEXT)
        perceived = perceived_ask.clean_fields(one.get(perceived_ask.FIELD)).get(perceived_ask.FIELD)
        specs.append(ItemSpec(title=title, text=text, state=state, group=one.get("group"), ask=ask, perceived_ask=perceived))
    return specs


def file_as_owner(ctx: CplugContext, entry_id: int, specs: Sequence[ItemSpec]) -> Dict[str, Any]:
    store, inboxes = service.store(ctx), InboxStore(service.store(ctx))
    entry = inboxes.get(entry_id)
    previous = inboxes.claim(entry_id, inbox.FILED, store._clock())
    items: List[Dict[str, Any]] = []
    try:
        for spec in specs:
            group = service.groups(ctx).find_or_create(entry["list"], spec.group, actor=rules.JOE)
            added = store.add(entry["list"], spec.text, actor=rules.JOE, title=spec.title, group=group, perceived_ask=spec.perceived_ask)
            inboxes.link_item(entry_id, added["id"])
            if spec.state == TODO:
                store.update(added["id"], actor=rules.JOE, state=TODO)
            items.append(store.item(added["id"]))
    except rules.TaskManagerError:
        if not items:
            inboxes.release(entry_id, previous)
        raise
    return {"entry": inboxes.get(entry_id), "items": items}

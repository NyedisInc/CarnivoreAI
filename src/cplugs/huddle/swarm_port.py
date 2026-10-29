
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.cplugs.huddle import card_line, lane, lineage, repeat_card, rich_ask, swarm_forms, swarm_stream, phone_mark, rules, service
from src.cplugs.huddle.cards import reads
from src.cplugs.huddle.cards.projection import card_shaped
from src.cplugs.huddle.rules import CLAUDE, JOE
from src.cplugs.sdk import CplugContext, chat_category
from src.cplugs.sdk.swarm import Messenger, SwarmError

logger = structlog.get_logger()

CHAT_REF = swarm_stream.CHAT_REF
CHAT_TEXT = "chat"
FLIPPED_NOTE = "flipped back to a task agent"
CLOSE_STATES = ("done", "answered", "flipped")


class TaskManagerSwarmPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx

    def _store(self) -> Any:
        return service.store(self._ctx)

    async def _run(self, call: Callable[[], Any]) -> Any:
        return await asyncio.to_thread(call)

    async def ensure_thread(self, thread_key: str, title: str) -> None:
        self._ctx.notify("list", rules.check_list_key(thread_key))

    async def post_card(self, thread_key: str, kind: str, title: str, text: str, swarm_ref: str) -> int:
        try:
            if repeat_card.is_counted(swarm_ref):
                listed = await self._run(lambda: self._store().list_items(thread_key))
                open_card = repeat_card.find_open(listed["items"], swarm_ref, title)
                if open_card is not None:
                    counted, _count = repeat_card.next_text(open_card["text"], text)
                    await self._run(lambda: self._store().update(open_card["id"], actor=JOE, text=counted))
                    return int(open_card["id"])
            item = await self._run(lambda: self._store().add(
                thread_key, text, actor=CLAUDE, kind=kind, title=title or None, created_key=rules.SWARM_KEY, swarm_ref=swarm_ref))
        except rules.TaskManagerError as exc:
            raise SwarmError(str(exc)) from exc
        await self._post_form(int(item["id"]), swarm_ref)
        return int(item["id"])

    async def check_form(self, questions: Any) -> str:
        try:
            flat, _parts = swarm_forms.check(questions)
        except rules.TaskManagerError as exc:
            raise SwarmError(str(exc)) from exc
        return flat

    async def stage_form(self, question_id: int, questions: Any) -> None:
        try:
            _flat, parts = swarm_forms.check(questions)
        except rules.TaskManagerError as exc:
            raise SwarmError(str(exc)) from exc
        await self._run(lambda: swarm_forms.stage(self._ctx.storage, question_id, parts))

    async def _post_form(self, item_id: int, swarm_ref: str) -> None:
        head, _, raw = swarm_ref.partition(":")
        if head != "question" or not raw.isdigit():
            return
        storage = self._ctx.storage
        parts = await self._run(lambda: swarm_forms.take(storage, int(raw)))
        if parts is None:
            return
        form = rich_ask.form_of(parts)
        if not form:
            logger.warning("swarm_form_unreadable", question_id=int(raw))
            return
        try:
            await self._run(lambda: self._store().post(item_id, rich_ask.flatten("", form), actor=CLAUDE, kind=rules.QUESTION, parts=parts))
        except rules.TaskManagerError as exc:
            logger.warning("swarm_form_not_posted", question_id=int(raw), item=item_id, error=str(exc)[:200])
            return
        await self._run(lambda: swarm_forms.drop(storage, int(raw)))

    async def _chat_item(self, thread_key: str) -> int:
        def find() -> Optional[int]:
            body = self._store().list_items(thread_key)
            return next((i["id"] for i in body["items"] if i["swarm_ref"] == CHAT_REF), None)

        found = await self._run(find)
        if found is not None:
            return int(found)
        item = await self._run(lambda: self._store().add(
            thread_key, CHAT_TEXT, actor=CLAUDE, kind=rules.NO_KIND, created_key=rules.SWARM_KEY, swarm_ref=CHAT_REF))
        return int(item["id"])

    async def post_owner_message(self, thread_key: str, text: str) -> str:
        item_id = await self._chat_item(thread_key)
        posted = await self._run(lambda: self._store().post(item_id, text, actor=JOE, kind=rules.REPLY,
                                                            author_key=rules.OWNER_KEY))
        return f"huddle:msg:{posted['message']['id']}"

    async def owner_message(self, thread_key: str, ref: str) -> Optional[str]:
        head, _, raw = ref.rpartition(":")
        if head != "huddle:msg" or not raw.isdigit():
            return None
        body = await self._run(lambda: self._store().list_items(thread_key))
        for item in body["items"]:
            if item["swarm_ref"] == CHAT_REF:
                for msg in item["thread"]:
                    if msg["id"] == int(raw) and msg["author"] == JOE and msg["author_key"] == rules.OWNER_KEY:
                        return str(msg["text"])
        return None

    async def post_agent_message(self, thread_key: str, text: str, author_key: str) -> str:
        item_id = await self._chat_item(thread_key)
        posted = await self._run(lambda: self._store().post(item_id, text, actor=CLAUDE, author_key=author_key))
        return f"huddle:msg:{posted['message']['id']}"

    async def post_traffic(self, thread_key: str, text: str, swarm_ref: str) -> str:
        category = chat_category.category_of_ref(swarm_ref)
        parts = card_line.parts_for(swarm_ref)
        item_id = await self._chat_item(thread_key)
        posted = await self._run(lambda: self._store().post(item_id, text, actor=CLAUDE, kind="info",
                                                            author_key=rules.SWARM_KEY, category=category, parts=parts))
        return f"huddle:msg:{posted['message']['id']}"

    async def mark_phone_sent(self, item_id: int) -> None:
        await self._run(lambda: phone_mark.mark(self._store(), item_id))

    async def close_card(self, item_id: int, state: str) -> None:
        if state not in CLOSE_STATES:
            raise ValueError(f"state must be one of {CLOSE_STATES}, not {state!r}")
        if card_shaped(await self._run(lambda: self._store().item(item_id))):
            raise SwarmError("this item is a swarm card; it moves to Done through the board or the swarm card tools")
        if state == "flipped":
            title = str((await self._run(lambda: self._store().item(item_id)))["title"] or "")
            name = title.split(": ", 1)[-1] if title.startswith("promoted: ") else title
            await self._run(lambda: self._store().update(
                item_id, actor=JOE, state=rules.DONE, note=FLIPPED_NOTE, title=f"flipped back: {name}".strip(),
                text=f"{name or 'the agent'} was flipped back to a task agent. Its memory moved back to local scope."))
        elif state == "done":
            await self._run(lambda: self._store().update(item_id, actor=JOE, state=rules.DONE))
        else:
            await self._run(lambda: self._store().mark_answered(item_id, actor=JOE))

    async def settle_cards(self, swarm_ref: str, *, prefix: bool = False, resolve: bool = False) -> None:
        if resolve:
            ids = await self._run(lambda: self._store().mark_sent_by_swarm_ref(swarm_ref, prefix=prefix))
            for item_id in ids:
                await self._run(lambda i=item_id: self._store().update(i, actor=JOE, state=rules.DONE,
                                                                     decided=lineage.Decided(lineage.CARNIVORE, lineage.CAUSE_GONE)))
        await self._run(lambda: self._store().mark_sent_by_swarm_ref(swarm_ref, prefix=prefix))

    async def close_open_cards(self, thread_key: str, prefix: str) -> None:
        def stale() -> List[int]:
            body = self._store().list_items(thread_key)
            return [i["id"] for i in body["items"]
                    if (i.get("swarm_ref") or "").startswith(prefix) and i.get("state") not in rules.APPROVED_STATES]

        for item_id in await self._run(stale):
            await self._close_card(item_id)

    async def _close_card(self, item_id: int) -> None:
        await self._run(lambda: self._store().update(item_id, actor=JOE, state=rules.DONE,
                                                     decided=lineage.Decided(lineage.CARNIVORE, lineage.SUPERSEDED)))
        await self._run(lambda: self._store().retire_swarm_ref(item_id))

    async def open_card_id(self, thread_key: str, swarm_ref: str) -> Optional[int]:
        body = await self._run(lambda: self._store().list_items(thread_key))
        return next((int(i["id"]) for i in body["items"] if i.get("swarm_ref") == swarm_ref and i.get("state") not in rules.APPROVED_STATES), None)

    async def open_cards(self) -> List[Dict[str, Any]]:
        return await self._run(self._store().open_swarm_cards)

    async def archive_thread(self, thread_key: str) -> None:
        def archive() -> None:
            store = self._store()
            with closing(store._read_connection()) as conn:
                kept = reads.in_use_ids(conn, thread_key)
            for item in store.list_items(thread_key)["items"]:
                if item["lane"] == lane.TASK_MANAGER:
                    continue
                if item["id"] not in kept:
                    store.delete(item["id"], actor=JOE)

        await self._run(archive)

    async def read_thread(self, thread_key: str, limit: int, *, cards: bool = True) -> List[Dict[str, Any]]:
        body = await self._run(lambda: self._store().list_items(thread_key))
        return swarm_stream.entries(body, cards=cards)[-limit:]

    async def tell(self, thread_key: str, session_id: str, text: str, *, message: Messenger) -> Any:
        told_at = await self._run(self._store().current_cursor)
        result = await message(session_id, text)
        target_key = (await self._ctx.sessions.durable_keys()).get(session_id) or session_id
        await self._run(lambda: self._store().record_send([thread_key], told_at, target_key))
        return result

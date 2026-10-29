
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Sequence

from src.cplugs.huddle import files, kinds, service, task_files
from src.cplugs.huddle.rules import JOE, REPLY, TaskManagerError
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk.swarm import SwarmError


class CardRefused(TaskManagerError):

    code = "swarm_card_refused"
    status = 409


async def decide_card(ctx: CplugContext, item: Dict[str, Any], decision: str, owner_message_ref: str = "", note: str = "", *,
                      structured: Optional[Dict[str, Any]] = None) -> None:
    ref = item.get("swarm_ref") or ""
    swarm = service.swarm_of(ctx)
    if not ref or ref == "chat" or swarm is None:
        return
    try:
        await swarm.card_decided(ref, decision, note, owner_message_ref, structured=structured)
    except SwarmError as exc:
        raise CardRefused(str(exc)) from exc


async def post_reply(ctx: CplugContext, item_id: int, text: str, *, file_ids: Sequence[str] = (), parts: Optional[str] = None,
                     ack_through: Optional[int] = None, comment: bool = False) -> Dict[str, Any]:
    def write() -> Dict[str, Any]:
        target = task_files.folder_for(ctx, item_id, task_files.PASTES) if file_ids and parts is None else None
        attached = files.parts_of(files.attach(ctx.storage, item_id, file_ids, target, task_files.search_dirs(item_id) if file_ids else ()))
        stored = parts if parts is not None else attached
        return service.store(ctx).post(item_id, text, actor=JOE, kind=kinds.COMMENT if comment else REPLY, parts=stored,
                                          allow_blank=bool(stored), ack_through=ack_through)

    posted = await asyncio.to_thread(write)
    if comment:
        return posted
    note = posted["message"]["text"] or ", ".join(f["name"] for f in posted["message"].get("files", []))
    await decide_card(ctx, posted["item"], "answer", f"huddle:msg:{posted['message']['id']}", note)
    return posted

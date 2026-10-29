
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.cplugs.huddle import item_owner, lineage
from src.cplugs.huddle.roles import route
from src.cplugs.huddle.roles.store import RoleStore

if TYPE_CHECKING:
    from src.cplugs.huddle.store import TaskManagerStore

logger = structlog.get_logger()

ME = "me"
DETAIL_TAG_GONE = "tag_gone"
DETAIL_SESSION_GONE = "session_gone"


class TagRefused(Exception):
    pass


def set_tag(store: "TaskManagerStore", item_id: int, key: str) -> Dict[str, Any]:
    with store._immediate() as conn:
        row = store._row(conn, item_id)
        if row[item_owner.TAG_COLUMN] == key:
            return store.item(item_id)
        conn.execute("UPDATE work_items SET tagged_session_key = ?, revision = revision + 1, seq = ?, updated_at = ? WHERE id = ?",
                     (key, store._next_seq(conn), store._clock(), item_id))
        list_key = row["list_key"]
    store._commit_notify(list_key)
    logger.info("task_manager_tagged", item=item_id, tagged=bool(key))
    return store.item(item_id)


def take_over(store: "TaskManagerStore", item_id: int, lead_key: str, detail: str = DETAIL_TAG_GONE, *, lost: str = "") -> bool:
    with store._immediate() as conn:
        row = store._row(conn, item_id)
        if lost:
            claimant = conn.execute("SELECT claude_working_by FROM work_items WHERE id = ?", (item_id,)).fetchone()[0]
            if lost not in (row[item_owner.COLUMN], claimant):
                return False
            clear_tag, detail = "", DETAIL_SESSION_GONE
        else:
            if not row[item_owner.TAG_COLUMN]:
                return False
            clear_tag = ", tagged_session_key = ''"
        conn.execute(f"UPDATE work_items SET owner_session_key = ?{clear_tag}, claude_working = 0, claude_working_by = '', "
                     "revision = revision + 1, seq = ?, updated_at = ? WHERE id = ?", (lead_key, store._next_seq(conn), store._clock(), item_id))
        lineage.record(conn, item_id, row["list_key"], row["state"], row["state"], by=lineage.CARNIVORE, now=store._clock(), detail=detail)
        list_key = row["list_key"]
    store._commit_notify(list_key)
    logger.info("task_manager_tag_taken_over", item=item_id, detail=detail)
    return True


async def target_key(ctx: Any, store: "TaskManagerStore", value: str, *, caller_key: Optional[str]) -> str:
    value = value.strip()
    if not value:
        return ""
    if value == ME:
        if not caller_key:
            raise TagRefused("tag me needs a session; an external token has none. Name an agent id from agents_lookup")
        return caller_key
    if value.startswith("remote:"):
        raise TagRefused("a task is tagged to a session on this computer; a paired computer's session cannot take a tag")
    infos = await ctx.sessions.list()
    keys = await ctx.sessions.durable_keys(infos)
    known = {*keys.values()}
    key = next((keys.get(i.session.id) or i.session.id for i in infos if value in (i.session.id, i.tmux_session)), None)
    if key is None and value in known:
        key = value
    if key is None:
        try:
            key = value if value in await route.asleep_read_keys(ctx) else None
        except (HTTPException, PermissionError) as exc:
            logger.warning("task_manager_tag_asleep_unreadable", error_type=type(exc).__name__, status=getattr(exc, "status_code", None))
    if key is None:
        raise TagRefused(f"no session {value} on this computer; look it up with agents_lookup")
    if key != caller_key and key in RoleStore(store).dnd_keys():
        raise TagRefused("that session is on do not disturb; ask the owner, or pick another agent")
    return key

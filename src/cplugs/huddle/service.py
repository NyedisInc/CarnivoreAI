
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

from src.cplugs.huddle import callers, lifecycle, question_toasts, reply_send, send_pick
from src.cplugs.huddle.cards import policy as card_policy
from src.cplugs.huddle.groups import GroupWriter
from src.cplugs.huddle.roles import route as roles_route
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.huddle.rules import ALL_LIST, TaskManagerNotFound, agent_id_of, list_order_id
from src.cplugs.huddle.store import TaskManagerStore
from src.cplugs.huddle.store_reads import empty_summary
from src.cplugs.sdk import CapabilityMissing, CplugContext

logger = structlog.get_logger()

QUESTION_TOAST_TITLE = "swarm: claude has a question"


def store(ctx: CplugContext) -> TaskManagerStore:
    view = ctx.settings.get("view", lifecycle.VIEW_STATUS)

    def changed(key: str) -> None:
        ctx.notify("list", key)
        ctx.notify("cards", key)
        swarm = swarm_of(ctx)
        if swarm is not None:
            swarm.thread_changed(key)
        kicked = card_policy.drain_kicks()
        if swarm is not None:
            for project_key in sorted(kicked):
                swarm.deal_requested(project_key)

    return TaskManagerStore(ctx.storage, notify=changed, view=view,
                       acted=lambda item_id: question_toasts.dismiss(ctx, item_id))


def groups(ctx: CplugContext) -> GroupWriter:
    return GroupWriter(store(ctx))


def swarm_of(ctx: CplugContext) -> Optional[Any]:
    try:
        return ctx.swarm
    except CapabilityMissing:
        return None


def project_names(ctx: CplugContext) -> Dict[str, str]:
    names = {str(p["id"]): p["name"] for p in ctx.projects.list()}
    swarm = swarm_of(ctx)
    return {**names, **(swarm.agent_names() if swarm is not None else {})}


def list_rows(summary: dict, names: Dict[str, str], nudging: Optional[Dict[str, bool]] = None,
              inboxing: Optional[Dict[str, bool]] = None) -> List[dict]:
    empty = empty_summary()
    stored = summary.get("lists", {})
    nudging, inboxing = nudging or {}, inboxing or {}
    rows = [{"key": ALL_LIST, "name": None, "project_id": None, "nudge": False, "inbox_via_session": False, **stored.get(ALL_LIST, empty)}]
    keys = sorted(set(names) | {k for k in stored if k != ALL_LIST}, key=lambda k: (names.get(k, "~").lower(), list_order_id(k)))
    for key in keys:
        rows.append({"key": key, "name": names.get(key), "project_id": None if agent_id_of(key) else int(key),
                     "nudge": nudging.get(key, key.isdigit()), "inbox_via_session": key.isdigit() and inboxing.get(key, True),
                     **stored.get(key, empty)})
    return rows


def aggregate_groups(body: dict, names: Dict[str, str]) -> List[dict]:
    groups = [{"list": g["list"], "name": names.get(g["list"]),
               "project_id": None if g["list"] == ALL_LIST or agent_id_of(g["list"]) else int(g["list"]),
               "revision": g["revision"], "groups": g.get("groups", []), **({"inbox": g["inbox"]} if "inbox" in g else {}),
               **({"done_count": g["done_count"]} if "done_count" in g else {}), "items": g["items"]} for g in body["groups"]]
    groups.sort(key=lambda g: (g["list"] != ALL_LIST, (g["name"] or "~").lower(), list_order_id(g["list"])))
    return groups


def _activity(info: Any) -> float:
    stamp = getattr(info.session, "last_activity", None)
    return stamp.timestamp() if isinstance(stamp, datetime) else 0.0


SEND_FAMILIES = ("claude", "codex")


def is_agent(info: Any) -> bool:
    family = (info.agent_family or "").lower()
    if family:
        return family in SEND_FAMILIES
    agent = (info.agent_type or info.session.agent_type or "").lower()
    return agent.startswith(SEND_FAMILIES)


def candidates(infos: List[Any], list_key: str, keys: Optional[Dict[str, str]] = None,
               agent_session: Optional[str] = None) -> List[dict]:
    agents = [i for i in infos if is_agent(i)]
    if agent_id_of(list_key):
        agents = [i for i in agents if i.session.id == agent_session]
        rows = agents
    else:
        rows = [i for i in agents if list_key == ALL_LIST or str(getattr(i, "project_id", None)) == list_key]
    elsewhere = not rows and list_key != ALL_LIST and not agent_id_of(list_key)
    if elsewhere:
        rows = agents
    rows.sort(key=_activity, reverse=True)
    return [{
        "id": i.session.id, "key": (keys or {}).get(i.session.id) or i.session.id,
        "label": _label(i, elsewhere), "tmux_session": i.tmux_session,
        "project": i.project_name, "activity_status": i.activity_status, "elsewhere": elsewhere,
        "last_activity": i.session.last_activity.isoformat() if isinstance(i.session.last_activity, datetime) else None,
    } for i in rows]


def reader_owns(infos: List[Any], session_id: str, list_key: str, agent_session: Optional[str] = None) -> bool:
    row = next((i for i in infos if i.session.id == session_id), None)
    if agent_id_of(list_key):
        return row is not None and agent_session == session_id
    return row is not None and (list_key == ALL_LIST or str(getattr(row, "project_id", None)) == list_key)


def _label(info: Any, elsewhere: bool) -> str:
    label = info.label or info.tmux_session or info.session.id
    return f"{label} ({info.project_name})" if elsewhere and info.project_name else label


async def agent_session(ctx: CplugContext, list_key: str) -> Optional[str]:
    swarm = swarm_of(ctx)
    if swarm is None or not agent_id_of(list_key):
        return None
    agent = await swarm.agent_for_list(list_key)
    return agent.session_id if agent else None


async def candidate_rows(ctx: CplugContext, list_key: str, infos: Optional[List[Any]] = None) -> List[dict]:
    rows = await ctx.sessions.list() if infos is None else infos
    return candidates(rows, list_key, await ctx.sessions.durable_keys(rows), await agent_session(ctx, list_key))


def send_choice(ctx: CplugContext, rows: List[dict], list_key: str) -> Dict[str, Any]:
    with ctx.storage.read_scope():
        return _send_choice(ctx, rows, list_key)


def _send_choice(ctx: CplugContext, rows: List[dict], list_key: str) -> Dict[str, Any]:
    pick = store(ctx).send_pick(list_key)
    chosen = next((r for r in rows if pick and r["key"] == pick), None)
    if chosen is not None:
        return {"list": list_key, "sessions": rows, "default": chosen["id"], "reason": send_pick.REASON_PICKED}
    if any(r.get("elsewhere") for r in rows):
        return {"list": list_key, "sessions": rows, "default": None, "reason": callers.REASON_PICK}
    huddle = store(ctx)
    dnd = RoleStore(huddle).dnd_keys()
    lead_id = roles_route.lead_target(huddle, rows, list_key)
    if lead_id is not None:
        return {"list": list_key, "sessions": rows, "default": lead_id, "reason": roles_route.REASON_LEAD}
    default, reason = callers.pick_default([(r["id"], r["key"]) for r in roles_route.without_dnd(rows, dnd)], list_key, callers.recent_callers(ctx.storage))
    return {"list": list_key, "sessions": rows, "default": default, "reason": reason}


def changed_lists(heads: Dict[str, int], cursors: Dict[str, Optional[int]],
                  names: Dict[str, str]) -> List[Tuple[str, Optional[str], int]]:
    rows = [(key, None if key == ALL_LIST else names.get(key), cursors.get(key) or 0)
            for key, head in heads.items() if head > (cursors.get(key) or 0)]
    return sorted(rows, key=lambda r: (r[0] != ALL_LIST, r[0]))


def changed_for(ctx: CplugContext, key: str, session_id: str, list_key: str) -> List[Tuple[str, Optional[str], int]]:
    st = store(ctx)
    heads = st.list_heads()
    cursors = {k: st.last_read(key, k, session_id) for k in heads}
    return changed_lists(heads, cursors, project_names(ctx))


def told_lists(ctx: CplugContext, list_key: str, changed: Optional[List[Tuple[str, Optional[str], int]]]) -> List[str]:
    if list_key != ALL_LIST:
        return [list_key]
    return sorted(set(store(ctx).list_heads()) | {k for k, _n, _c in changed or []})


def known_list_key(ctx: CplugContext, key: str) -> str:
    if key != ALL_LIST and key not in project_names(ctx):
        raise TaskManagerNotFound(f"no project {key}")
    return key


def _where(key: str, name: Optional[str]) -> str:
    return "the shared swarm list" if key == ALL_LIST else f"the swarm list for {name or 'project ' + key}"


def send_text(list_key: str, name: Optional[str], since: Optional[int],
              changed: Optional[List[Tuple[str, Optional[str], int]]] = None, items: Optional[Sequence[int]] = None,
              replies: Sequence[reply_send.Reply] = ()) -> str:
    return _send_line(list_key, name, since, changed, items) + reply_send.sentence(replies)


def _send_line(list_key: str, name: Optional[str], since: Optional[int],
               changed: Optional[List[Tuple[str, Optional[str], int]]], items: Optional[Sequence[int]]) -> str:
    cursor = since if since is not None else 0
    what = "changed" + (f" (item ids {', '.join(str(i) for i in items)})" if items else "")
    if list_key != ALL_LIST:
        return (f"{_where(list_key, name)} {what}: read it with the carnivore task_manager_changes tool "
                f"(list {list_key}, since {cursor}) and answer there.")
    if not changed:
        return (f"the swarm {what}: read it with the carnivore task_manager_changes tool "
                f"(omit list to read every list, since {cursor}) and answer there.")
    where = " and ".join(_where(k, n) for k, n, _ in changed)
    calls = "; ".join(f"list {k}, since {c}" for k, _, c in changed)
    return f"{where} {what}: read {'it' if len(changed) == 1 else 'each'} with the carnivore task_manager_changes tool ({calls}) and answer there."


def owner_replies(ctx: CplugContext, list_key: str, since: Optional[int], changed: Optional[List[Tuple[str, Optional[str], int]]],
                  items: Optional[Sequence[int]] = None) -> List[reply_send.Reply]:
    st = store(ctx)
    lists = [(k, c) for k, _n, c in changed] if changed else [(list_key, since or 0)]
    return [r for k, c in lists
            for r in st.owner_replies(k, c, items if items is not None else [i for i, _o in st.untold_owners(k)])]


def surface_question(ctx: CplugContext, session_id: str, item_id: int, message_id: int) -> bool:
    ref = ctx.toast(session_id, QUESTION_TOAST_TITLE) if session_id else None
    if ref:
        question_toasts.remember(item_id, message_id, ref)
    return bool(ref)

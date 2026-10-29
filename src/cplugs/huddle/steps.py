
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Iterable, List, Sequence

from pydantic import BaseModel

from src.cplugs.sdk.session_tasks import SessionTasks

WATCH_KEY = "huddle"


class Steps(BaseModel):
    """The watch needs a model to sign: the answer of :func:`build`, as ``{lists: {...}}``."""

    lists: Dict[str, Any] = {}


Load = Callable[[Any], Awaitable[SessionTasks]]


def is_open(tasks: SessionTasks) -> bool:
    return tasks.state == "ok" and (tasks.counts.pending + tasks.counts.in_progress) > 0


def _entry(tasks: SessionTasks) -> Dict[str, Any]:
    return {"tasks": [t.model_dump() for t in tasks.tasks], "counts": tasks.counts.model_dump()}


async def build(claims: Iterable[Sequence[Any]], infos: List[Any], keys: Dict[str, str], load: Load) -> Dict[str, Any]:
    by_key = {keys.get(i.session.id, i.session.id): i for i in infos}
    by_key.update({i.session.id: i for i in infos})
    lists: Dict[str, Dict[str, Any]] = {}
    for item_id, list_key, claimant in claims:
        info = by_key.get(claimant)
        if info is None:
            continue
        tasks = await load(info)
        if is_open(tasks):
            lists.setdefault(list_key, {"items": {}})["items"][str(item_id)] = _entry(tasks)
    return {"lists": lists}

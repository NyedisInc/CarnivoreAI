
from __future__ import annotations

from typing import Any, Dict

from src.cplugs.huddle import service
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.huddle.nudge_store import NudgeStore
from src.cplugs.sdk import CplugContext


def build_lists(ctx: CplugContext, *, hide_swarm: bool) -> Dict[str, Any]:
    store = service.store(ctx)
    summary = store.summary(hide_swarm=hide_swarm)
    names = service.project_names(ctx)
    return {"cursor": summary["cursor"],
            "lists": service.list_rows(summary, names, NudgeStore(store).prefs(), InboxStore(store).prefs())}

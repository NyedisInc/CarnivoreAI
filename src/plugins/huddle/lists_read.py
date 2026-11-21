
from __future__ import annotations

from typing import Any, Dict

from src.plugins.huddle import service
from src.plugins.huddle.inbox_store import InboxStore
from src.plugins.huddle.nudge_store import NudgeStore
from src.plugins.sdk import CplugContext


def build_lists(ctx: CplugContext, *, hide_swarm: bool) -> Dict[str, Any]:
    store = service.store(ctx)
    summary = store.summary(hide_swarm=hide_swarm)
    names = service.project_names(ctx)
    return {"cursor": summary["cursor"],
            "lists": service.list_rows(summary, names, NudgeStore(store).prefs(), InboxStore(store).prefs())}

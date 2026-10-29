from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel, ConfigDict, Field

from src.config import settings
from src.core.automations.scrooge import ai_pass, numbers, report, rules
from src.core.db import connect, db_path_for
from src.core.stats import config as stats_config


class RecipeFailed(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RecipeSkipped(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ScroogeParams(BaseModel):
    """Scrooge's params: projects worked on within ``active_days`` are read over the same window."""

    model_config = ConfigDict(extra="forbid")
    active_days: int = Field(default=numbers.ACTIVE_DAYS, ge=1, le=90)


def _open_db() -> sqlite3.Connection:
    conn = connect(db_path_for(settings.get_state_dir()), create=False)
    conn.row_factory = sqlite3.Row
    return conn


def _gather(store: Any, params: ScroogeParams, now: datetime) -> Tuple[Dict[str, Any], Dict[int, dict], List[Tuple[str, str, str]]]:
    with closing(_open_db()) as conn:
        data = numbers.collect_numbers(store, conn, now=now, active_days=params.active_days)
    globals_ = rules.read_global_rules()
    summaries: Dict[int, dict] = {}
    texts = [("global", item.label, item.text) for item in globals_ if item.text is not None]
    for project in data["projects"]:
        files = rules.read_project_rules(Path(project["folder"]))
        summaries[project["project_id"]] = rules.summarize_rules(files, globals_)
        texts += [(project["name"], item.label, item.text) for item in files if item.text is not None]
    return data, summaries, texts


async def run_scrooge(ctx: Any, params: ScroogeParams) -> Tuple[Dict[str, Any], Optional[float]]:
    store = getattr(ctx.app_state, "stats_store", None)
    if store is None:
        raise RecipeFailed("stats_unavailable")
    now = datetime.now(timezone.utc)
    try:
        data, summaries, texts = await asyncio.to_thread(_gather, store, params, now)
    except stats_config.StatsOff as exc:
        raise RecipeFailed("stats_off") from exc
    ai = await ai_pass.run_ai_pass(data, texts)
    return report.build_report(data, summaries, ai, now), ai.cost_usd


Recipe = Tuple[Type[BaseModel], Callable[[Any, Any], Awaitable[Tuple[Dict[str, Any], Optional[float]]]]]
REGISTRY: Dict[str, Recipe] = {"scrooge": (ScroogeParams, run_scrooge)}


def lookup(name: str) -> Optional[Recipe]:
    from src.core.automations import system_actions  # noqa: PLC0415

    return REGISTRY.get(name) or system_actions.REGISTRY.get(name)

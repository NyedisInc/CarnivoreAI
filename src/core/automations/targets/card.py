
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Any, Dict, Optional

import structlog

from src.core.automations import models as m
from src.core.automations import recipes
from src.core.automations import notify_policy
from src.core.swarm import switch as swarm_switch
from src.core.swarm.cards import ops
from src.cplugs.sdk.cards import CardRefused
from src.core.project_writes import list_projects_ordered

logger = structlog.get_logger()
_TEXT_FIELDS = ("title", "summary", "text", "how_to_validate")
R_CARD_REFUSED = "card_refused"
R_SWARM_OFF = "swarm_off"


def expand(text: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now().astimezone()
    iso = now.isocalendar()
    return text.replace("{date}", now.strftime("%Y-%m-%d")).replace("{week}", f"{iso[0]}-W{iso[1]:02d}")


def validate_target(target: Dict[str, Any]) -> Optional[str]:
    try:
        with closing(recipes._open_db()) as conn:
            rows = list_projects_ordered(conn, include_archived=True)
    except (OSError, sqlite3.Error):
        return "project_missing"
    mine = [r for r in rows if r.get("id") == target["project_id"]]
    if not mine:
        return "project_missing"
    return "project_archived" if mine[0].get("archived_at") else None


async def run(ctx: Any, automation: Dict[str, Any], run_row: Dict[str, Any]) -> m.RunOutcome:
    if not swarm_switch.is_on():
        return m.RunOutcome(status=m.SKIPPED, reason=R_SWARM_OFF)
    outcome = await _create(ctx, automation, run_row)
    failed = outcome.status != m.SUCCEEDED
    notice = notify_policy.decide(automation, failed)
    if notice:
        notify_policy.tell(notice, automation, run_row["run_id"], ctx.store)
    return outcome


async def _create(ctx: Any, automation: Dict[str, Any], run_row: Dict[str, Any]) -> m.RunOutcome:
    target = automation["target"]
    now = datetime.now().astimezone()
    fields = {name: expand(str(target.get(name) or ""), now) for name in _TEXT_FIELDS}
    args = {**fields, "project_id": target["project_id"], "queued": bool(target.get("queued"))}

    if not fields["title"].strip() or len(fields["title"].strip()) > ops.MAX_TITLE_CHARS \
            or len(" ".join(fields["summary"].split())) > ops.MAX_SUMMARY_CHARS:
        return m.RunOutcome(status=m.FAILED, reason=m.R_TARGET_INVALID)
    try:
        card = await ops.create(ctx.app_state, None, args, by="owner")
    except CardRefused as exc:
        logger.info("automation_card_refused", run_id=run_row["run_id"], code=exc.code)
        return m.RunOutcome(status=m.FAILED, reason=m.R_TARGET_INVALID if exc.code == "bad_card" else R_CARD_REFUSED)
    return m.RunOutcome(status=m.SUCCEEDED, report={"card_id": card["id"], "column": card["column"], "project_id": target["project_id"]})

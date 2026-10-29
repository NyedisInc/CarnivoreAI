
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import structlog

from src.core import db
from src.core.swarm import settings, store

logger = structlog.get_logger()

CLOSEOUT_PREFIX = "closeout:"


def cutoff(now: datetime, minutes: int) -> str:
    return (now - timedelta(minutes=minutes)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def waiting(conn: sqlite3.Connection, *, parent_id: Any = None, older_than: str = "") -> List[Dict[str, Any]]:
    out = []
    for rep in store.list_reports(conn, parent_id=parent_id):
        if older_than and str(rep["created_at"]) >= older_than:
            continue
        agent = store.get_agent(conn, rep["agent_id"])
        if agent is not None and agent["rank"] == "task" and agent["torn_down_at"] is None:
            out.append({**agent, "report_id": rep["id"]})
    return out


def _busy(conn: sqlite3.Connection, agent_id: int) -> bool:
    asked = conn.execute("SELECT 1 FROM swarm_question_askers k JOIN swarm_questions q ON q.id = k.question_id "
                         "WHERE k.agent_id = ? AND q.state IN ('routing', 'reopened') LIMIT 1", (agent_id,)).fetchone()
    return store.live_body_count(conn, agent_id) > 0 or asked is not None


_OUTCOME_TEXT = {"torn_down": "so the server accepted its report and tore it down",
                 "promotion_candidate": "and its task type earned a promotion, so the server accepted its report and it sleeps: "
                                        "promote it with swarm_promote, or tear it down with swarm_promote and decision teardown"}


async def sweep(app_state: Any, now: datetime | None = None) -> int:
    from src.core.swarm import body, reports

    cfg = settings.read_current()
    cutoff_at, teardown = cutoff(now or datetime.now(timezone.utc), cfg.closeout_window_minutes), cfg.closeout_default == "teardown"
    states = ("awake", "asleep") if teardown else ("awake",)
    try:
        due = await body.run_db(lambda c: [a for a in waiting(c, older_than=cutoff_at) if a["state"] in states and not _busy(c, a["id"])])
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.warning("swarm_closeout_sweep_unreadable", error_type=type(exc).__name__)
        return 0
    closed = 0
    for agent in due:
        try:
            if teardown:
                parent = await body.run_db(lambda c: store.get_agent(c, agent["parent_id"]))
                found = await body.run_db(lambda c: store.get_report(c, agent["report_id"]))
                if parent is None or found is None or found["state"] != "pending":
                    continue
                outcome = (await reports.decide(app_state, parent, found, "accept"))["outcome"]
            else:
                await body.sleep(app_state, agent["id"], "auto_sleep")
                outcome = "asleep"
        except (body.BodyError, reports.ReportRefused) as exc:
            logger.info("swarm_closeout_refused", agent_id=agent["id"], error=str(exc)[:200])
            continue
        closed += 1
        tail = _OUTCOME_TEXT.get(outcome, "so it is asleep now. Close it out: accept the report to tear it down, or promote it to a "
                                          "feature agent and let it sleep.")
        await body._card(agent, f"close out: {agent['display_name']}",
                         f"{agent['display_name']} finished (report {agent['report_id']}) and nobody closed it out, {tail}",
                         f"{CLOSEOUT_PREFIX}{agent['report_id']}")
        logger.info("swarm_closeout_backstop", agent_id=agent["id"], report_id=agent["report_id"], outcome=outcome)
    return closed

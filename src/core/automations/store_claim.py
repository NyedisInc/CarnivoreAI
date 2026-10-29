
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import structlog

from src.core.automations import contract, gates, schedule
from src.core.automations import models as m
from src.core.automations import run_title, scheduler_log
from src.core.automations.store_schema import Tx, next_number
from src.core.computers.this_label import this_label
from src.core.resource_push import topics
from src.core.timers.cron import parse_cron

logger = structlog.get_logger()


class ClaimMixin:

    def claim_due(self, now: float, boot_id: str) -> List[Dict[str, Any]]:
        claimed: List[str] = []
        logged: List[tuple] = []
        with self._write(nudge=False) as tx:
            due = tx.execute("SELECT * FROM automations WHERE enabled = 1 AND ((next_fire_at IS NOT NULL AND next_fire_at <= ?) "
                             "OR (retry_due_at IS NOT NULL AND retry_due_at <= ?)) ORDER BY COALESCE(next_fire_at, retry_due_at)",
                             (now, now)).fetchall()
            for row in due:
                automation_id, slot = row["automation_id"], row["next_fire_at"]
                tx.hit.add(topics.AUTOMATIONS)
                if slot is not None and slot <= now:
                    upcoming = self._advance(row["cron"], now, automation_id)
                    tx.execute("UPDATE automations SET next_fire_at = ? WHERE automation_id = ?", (upcoming, automation_id))
                    logged.append(("scheduled", {"automation_id": automation_id, "next_fire_at": upcoming}))
                    late = now - slot > m.GRACE_S
                    if late and row["misfire"] != contract.MISFIRE_RUN_ONCE:
                        run_id = self._fold_skip(tx, automation_id, m.R_MISSED, slot, now)
                        logged.append(("skipped", {"automation_id": automation_id, "run_id": run_id, "reason": m.R_MISSED,
                                                   "slot_at": slot}))
                    else:
                        tx.execute("UPDATE automations SET retry_due_at = NULL, retry_attempt = 0 WHERE automation_id = ?",
                                   (automation_id,))
                        trigger = "catch_up" if late else "schedule"
                        claimed.append(self._insert_claimed(tx, automation_id, trigger, slot, boot_id, now, 1))
                        logged.append(("catch_up" if late else "claimed", {"automation_id": automation_id, "run_id": claimed[-1],
                                                                          "trigger": trigger, "slot_at": slot, "attempt": 1}))
                        continue
                retry_at = row["retry_due_at"]
                if retry_at is not None and retry_at <= now:
                    tx.execute("UPDATE automations SET retry_due_at = NULL WHERE automation_id = ?", (automation_id,))
                    claimed.append(self._insert_claimed(tx, automation_id, "retry", retry_at, boot_id, now,
                                                        int(row["retry_attempt"]) + 1))
                    logged.append(("claimed", {"automation_id": automation_id, "run_id": claimed[-1], "trigger": "retry",
                                               "attempt": int(row["retry_attempt"]) + 1}))
        for event, fields in logged:
            scheduler_log.write(event, **fields)
        return [self.run(r) for r in claimed]

    @staticmethod
    def _insert_claimed(tx: Tx, automation_id: str, trigger: str, slot: Optional[float], boot_id: str, now: float,
                        attempt: int) -> str:
        run_id = f"run_{uuid.uuid4().hex}"
        tx.execute("INSERT INTO runs (run_id, automation_id, trigger, slot_at, status, boot_id, created_at, attempt, number, host) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)", (run_id, automation_id, trigger, slot, m.CLAIMED, boot_id, now, attempt,
                                                    next_number(tx, automation_id), this_label()))
        tx.hit.add(topics.AUTOMATION_RUNS)
        return run_id

    def settle_retry(self, automation_id: str, failed: bool, now: float) -> Optional[float]:
        with self._write() as tx:
            row = tx.execute("SELECT enabled, target, retry_max, retry_backoff_s, retry_attempt FROM automations "
                             "WHERE automation_id = ?", (automation_id,)).fetchone()
            if row is None:
                return None
            target = json.loads(row["target"])
            armed: Optional[tuple] = None
            if failed and row["enabled"] and row["retry_attempt"] < row["retry_max"] and not gates.spends(target):
                due = now + float(row["retry_backoff_s"])
                tx.execute("UPDATE automations SET retry_due_at = ?, retry_attempt = retry_attempt + 1 WHERE automation_id = ?",
                           (due, automation_id))
                tx.hit.add(topics.AUTOMATIONS)
                armed = (due, int(row["retry_attempt"]) + 1)
            else:
                tx.execute("UPDATE automations SET retry_due_at = NULL, retry_attempt = 0 WHERE automation_id = ?", (automation_id,))
                armed = None
        if armed is None:
            return None
        scheduler_log.write("retried", automation_id=automation_id, retry_due_at=armed[0], retry=armed[1])
        return armed[0]

    @staticmethod
    def _advance(cron: str, now: float, automation_id: str) -> Optional[float]:
        try:
            return schedule.next_epoch(parse_cron(cron), now)
        except ValueError as exc:
            logger.error("automation_cron_unusable", automation_id=automation_id, error=str(exc)[:100])
            return None

    @staticmethod
    def _fold_skip(tx: Tx, automation_id: str, reason: str, slot: Optional[float], now: float, trigger: str = "schedule") -> str:
        last = tx.execute("SELECT run_id, status, reason, trigger FROM runs WHERE automation_id = ? ORDER BY seq DESC LIMIT 1",
                          (automation_id,)).fetchone()
        tx.hit.add(topics.AUTOMATION_RUNS)
        if (trigger == "schedule" and last is not None and last["status"] == m.SKIPPED and last["reason"] == reason
                and last["trigger"] == "schedule"):
            tx.execute("UPDATE runs SET skip_count = skip_count + 1, last_slot_at = ?, ended_at = ? WHERE run_id = ?",
                       (slot, now, last["run_id"]))
            return last["run_id"]
        run_id = f"run_{uuid.uuid4().hex}"
        owner = tx.execute("SELECT name, target FROM automations WHERE automation_id = ?", (automation_id,)).fetchone()
        title, summary = run_title.build(name=owner["name"] if owner else "", status=m.SKIPPED, reason=reason,
                                         kind=json.loads(owner["target"]).get("kind") if owner else None)
        tx.execute("INSERT INTO runs (run_id, automation_id, trigger, slot_at, status, reason, skip_count, first_slot_at, "
                   "last_slot_at, ended_at, created_at, number, host, title, summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, automation_id, trigger, slot, m.SKIPPED, reason, 1, slot, slot, now, now,
                    next_number(tx, automation_id), this_label(), title, summary))
        return run_id

    def finish_skip(self, run_id: str, reason: str) -> str:
        now = self._clock()
        with self._write() as tx:
            row = tx.execute("SELECT automation_id, slot_at, trigger FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise m.AutomationNotFound(run_id)
            tx.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return self._fold_skip(tx, row["automation_id"], reason, row["slot_at"], now, row["trigger"])

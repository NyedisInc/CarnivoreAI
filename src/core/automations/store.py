
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

import structlog

from src.core import resource_push
from src.core.automations import models as m
from src.core.automations import scheduler_log
from src.core.automations import run_title
from src.core.automations import attachments, changes, contract, gates, schedule, targets
from src.core.automations.store_claim import ClaimMixin
from src.core.automations.report_empty import report_is_empty
from src.core.automations.store_schema import JSON_RUN, Tx, automation_row, closing, next_number, run_row
from src.core.computers.this_label import this_label
from src.core.resource_push import topics
from src.core.timers.redact import redact
from src.cplugs.sdk.storage import CplugStorage

logger = structlog.get_logger()

SAVE_CHECKED = ("blueprint_launch", "session_message", "command", "sequence")
_RUN_FIELDS = frozenset({"status", "reason", "started_at", "ended_at", "cost_usd", "sessions", "child", "report", "notes", "error",
                         "usage", "delivered", "attachments", "title", "summary"})
_UPDATE_FIELDS = frozenset({"name", "cron", "target", "delivery", "enabled"}) | contract.CONTRACT_FIELDS


def _check_recipe_params(target: Dict[str, Any]) -> None:
    from pydantic import ValidationError  # noqa: PLC0415

    from src.core.automations import recipes  # noqa: PLC0415

    found = recipes.lookup(target["recipe"])
    if found is None:
        raise m.AutomationInvalid("target_not_available", target["recipe"])
    try:
        found[0].model_validate(target.get("params") or {})
    except ValidationError as exc:
        raise m.AutomationInvalid("target_invalid", str(exc)[:300]) from exc


class AutomationStore(ClaimMixin):

    def __init__(self, storage: CplugStorage, clock: Callable[[], float] = time.time,
                 notify: Callable[[str], None] = resource_push.notify,
                 on_change: Optional[Callable[[], None]] = None) -> None:
        self._storage = storage
        self._clock = clock
        self._notify = notify
        self.on_change = on_change

    @contextmanager
    def _write(self, *hit: str, nudge: bool = True) -> Iterator[Tx]:
        tx = Tx(self._storage.connect(True), set(hit))
        try:
            tx.conn.execute("BEGIN IMMEDIATE")
            try:
                yield tx
                tx.conn.commit()
            except BaseException:
                tx.conn.rollback()
                raise
        finally:
            tx.conn.close()
        for topic in sorted(tx.hit):
            self._notify(topic)
        if nudge and tx.hit and self.on_change is not None:
            self.on_change()

    def _read(self) -> sqlite3.Connection:
        return self._storage.connect_read()

    @staticmethod
    def _next_fire(cron: str, enabled: bool, after: float) -> Optional[float]:
        compiled = schedule.compile_cron(cron, after)
        return schedule.next_epoch(compiled, after) if enabled else None

    def create(self, *, name: str, cron: str, target: Dict[str, Any], delivery: Optional[Dict[str, Any]] = None,
               enabled: bool = True, created_by: str = "app", seed_key: Optional[str] = None, description: str = "",
               project_id: Optional[int] = None, misfire: str = contract.MISFIRE_NEW_DEFAULT, retry_max: int = 0,
               retry_backoff_s: int = contract.RETRY_BACKOFF_DEFAULT_S, max_runtime_s: Optional[int] = None,
               actor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        name = (name or "").strip()
        if not 1 <= len(name) <= 80:
            raise m.AutomationInvalid("name_invalid", "1 to 80 characters")
        clean_target = self._checked_target(target)
        clean_delivery = m.validate_delivery(delivery)
        values = self._contract({"description": description, "project_id": project_id, "misfire": misfire,
                                 "retry_max": retry_max, "retry_backoff_s": retry_backoff_s, "max_runtime_s": max_runtime_s},
                                clean_target)
        who = json.dumps(actor or {"kind": created_by})
        now = self._clock()
        fire = self._next_fire(cron, enabled, now)
        automation_id = f"aut_{uuid.uuid4().hex}"
        row = {"automation_id": automation_id, "name": name, "name_key": name.casefold(), "enabled": int(enabled), "cron": cron,
               "target": json.dumps(clean_target), "delivery": json.dumps(clean_delivery), "next_fire_at": fire, "revision": 1,
               "created_by": created_by, "seed_key": seed_key, "created_at": now, "updated_at": now, **values,
               "created_actor": who, "updated_by": created_by, "updated_actor": who}
        with self._write(topics.AUTOMATIONS) as tx:
            try:
                tx.execute(f"INSERT INTO automations ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
            except sqlite3.IntegrityError as exc:
                raise m.AutomationInvalid("name_taken", name) from exc
            saved = automation_row(tx.execute("SELECT * FROM automations WHERE automation_id = ?", (automation_id,)).fetchone())
            changes.record(tx.conn, automation_id, "create", now, json.loads(who), None, saved)
        scheduler_log.write("created", automation_id=automation_id, name=name, actor=json.loads(who))
        scheduler_log.write("scheduled", automation_id=automation_id, next_fire_at=fire)
        return self.get(automation_id)

    @staticmethod
    def _contract(fields: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
        retry_max, backoff = contract.clean_retry(fields["retry_max"], fields["retry_backoff_s"])
        if retry_max and gates.spends(target):
            raise m.AutomationInvalid("retry_not_allowed", "only a target that spends no plan usage is retried")
        return {"description": contract.clean_description(fields["description"]),
                "project_id": contract.clean_project_id(fields["project_id"]),
                "misfire": contract.clean_misfire(fields["misfire"]), "retry_max": retry_max, "retry_backoff_s": backoff,
                "max_runtime_s": contract.clean_max_runtime(fields["max_runtime_s"])}

    @staticmethod
    def _checked_target(target: Any) -> Dict[str, Any]:
        clean = m.validate_target(target)
        for part in [clean, *(clean.get("steps") or ())]:
            if part["kind"] not in targets.RUNNERS:
                raise m.AutomationInvalid("target_not_available", part["kind"])
            if part["kind"] == "recipe":
                _check_recipe_params(part)
        check = targets.VALIDATORS.get(clean["kind"]) if clean["kind"] in SAVE_CHECKED else None
        if check is not None:
            problem = check(clean)
            if problem:
                raise m.AutomationInvalid("target_invalid", problem)
        return clean

    def get(self, automation_id: str) -> Dict[str, Any]:
        with closing(self._read()) as conn:
            row = conn.execute("SELECT * FROM automations WHERE automation_id = ?", (automation_id,)).fetchone()
        if row is None:
            raise m.AutomationNotFound(automation_id)
        return automation_row(row)

    def list_all(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        where, args = ("WHERE project_id = ? ", (project_id,)) if project_id is not None else ("", ())
        with closing(self._read()) as conn:
            return [automation_row(r) for r in conn.execute(f"SELECT * FROM automations {where}ORDER BY created_at, automation_id", args)]

    def changes(self, automation_id: str, limit: int = 50, before_seq: Optional[int] = None) -> List[Dict[str, Any]]:
        with closing(self._read()) as conn:
            return changes.read(conn, automation_id, limit, before_seq)

    def update(self, automation_id: str, revision: Optional[int], *, actor: Optional[Dict[str, Any]] = None,
               **fields: Any) -> Dict[str, Any]:
        unknown = set(fields) - _UPDATE_FIELDS
        if unknown:
            raise m.AutomationInvalid("field_unknown", ",".join(sorted(unknown)))
        now = self._clock()
        with self._write(topics.AUTOMATIONS) as tx:
            row = tx.execute("SELECT * FROM automations WHERE automation_id = ?", (automation_id,)).fetchone()
            if row is None:
                raise m.AutomationNotFound(automation_id)
            if revision is not None and revision != row["revision"]:
                raise m.RevisionConflict(automation_id)
            current = automation_row(row)
            name = (fields.get("name", current["name"]) or "").strip()
            if not 1 <= len(name) <= 80:
                raise m.AutomationInvalid("name_invalid", "1 to 80 characters")
            cron = fields.get("cron", current["trigger"]["cron"])
            enabled = bool(fields.get("enabled", current["enabled"]))
            clean_target = self._checked_target(fields["target"]) if "target" in fields else current["target"]
            clean_delivery = m.validate_delivery(fields["delivery"]) if "delivery" in fields else current["delivery"]
            values = self._contract({k: fields.get(k, current[k]) for k in contract.CONTRACT_FIELDS}, clean_target)
            who = actor or {"kind": "app"}
            fire = self._next_fire(cron, enabled, now)
            sets = {"name": name, "name_key": name.casefold(), "enabled": int(enabled), "cron": cron, "target": json.dumps(clean_target),
                    "delivery": json.dumps(clean_delivery), "next_fire_at": fire, "updated_at": now, **values,
                    "updated_by": who["kind"], "updated_actor": json.dumps(who)}
            try:
                tx.execute(f"UPDATE automations SET {', '.join(f'{k}=?' for k in sets)}, revision=revision+1 WHERE automation_id=?",
                           (*sets.values(), automation_id))
            except sqlite3.IntegrityError as exc:
                raise m.AutomationInvalid("name_taken", name) from exc
            saved = automation_row(tx.execute("SELECT * FROM automations WHERE automation_id = ?", (automation_id,)).fetchone())
            changes.record(tx.conn, automation_id, "update", now, who, current, saved)
        scheduler_log.write("edited", automation_id=automation_id, name=name, actor=who, fields=sorted(fields))
        scheduler_log.write("scheduled", automation_id=automation_id, next_fire_at=fire)
        return self.get(automation_id)

    def seed_settled(self, seed_key: str) -> bool:
        with closing(self._read()) as conn:
            row = conn.execute("SELECT 1 FROM automations WHERE seed_key = ? UNION ALL SELECT 1 FROM seed_tombstones "
                               "WHERE seed_key = ?", (seed_key, seed_key)).fetchone()
        return row is not None

    def set_enabled(self, automation_id: str, enabled: bool) -> Dict[str, Any]:
        return self.update(automation_id, None, enabled=enabled)

    def delete(self, automation_id: str, actor: Optional[Dict[str, Any]] = None) -> None:
        with self._write(topics.AUTOMATIONS, topics.AUTOMATION_RUNS) as tx:
            row = tx.execute("SELECT * FROM automations WHERE automation_id = ?", (automation_id,)).fetchone()
            if row is None:
                raise m.AutomationNotFound(automation_id)
            changes.record(tx.conn, automation_id, "delete", self._clock(), actor or {"kind": "app"}, automation_row(row), None)
            if row["seed_key"]:
                tx.execute("INSERT OR REPLACE INTO seed_tombstones VALUES (?, ?)", (row["seed_key"], self._clock()))
            doomed = [r["run_id"] for r in tx.execute("SELECT run_id FROM runs WHERE automation_id = ?", (automation_id,))]
            tx.execute("DELETE FROM automations WHERE automation_id = ?", (automation_id,))
        attachments.remove(self.attachments_root, doomed)
        scheduler_log.write("deleted", automation_id=automation_id, name=row["name"], actor=actor or {"kind": "app"})

    def next_due(self) -> Optional[float]:
        with closing(self._read()) as conn:
            row = conn.execute("SELECT MIN(MIN(COALESCE(next_fire_at, retry_due_at), COALESCE(retry_due_at, next_fire_at))) AS due "
                               "FROM automations WHERE enabled = 1").fetchone()
        return row["due"]

    def run(self, run_id: str) -> Dict[str, Any]:
        with closing(self._read()) as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise m.AutomationNotFound(run_id)
        return run_row(row)

    def runs(self, automation_id: Optional[str] = None, limit: int = 50, before: Optional[str] = None) -> List[Dict[str, Any]]:
        where, args = [], []
        if automation_id:
            where.append("automation_id = ?")
            args.append(automation_id)
        if before:
            where.append("seq < COALESCE((SELECT seq FROM runs WHERE run_id = ?), 0)")
            args.append(before)
        sql = "SELECT * FROM runs" + (" WHERE " + " AND ".join(where) if where else "")
        with closing(self._read()) as conn:
            return [run_row(r) for r in conn.execute(sql + " ORDER BY seq DESC LIMIT ?", (*args, max(1, min(limit, m.RUNS_KEPT))))]

    def latest_stopped_runs(self) -> Dict[str, Dict[str, Any]]:
        busy = (m.CLAIMED, m.RUNNING)
        marks = ",".join("?" * len(busy))
        sql = (f"SELECT r.* FROM runs r WHERE r.seq = (SELECT MAX(seq) FROM runs WHERE automation_id = r.automation_id "
               f"AND status NOT IN ({marks}))")
        with closing(self._read()) as conn:
            return {r["automation_id"]: run_row(r) for r in conn.execute(sql, busy)}

    def live_runs(self) -> List[Dict[str, Any]]:
        marks = ",".join("?" * len(m.LIVE_STATUSES))
        with closing(self._read()) as conn:
            return [run_row(r) for r in conn.execute(f"SELECT * FROM runs WHERE status IN ({marks}) ORDER BY seq", m.LIVE_STATUSES)]

    def insert_run(self, automation_id: str, boot_id: str, trigger: str = "run_now") -> Dict[str, Any]:
        now = self._clock()
        run_id = f"run_{uuid.uuid4().hex}"
        marks = ",".join("?" * len(m.LIVE_STATUSES))
        with self._write(topics.AUTOMATION_RUNS) as tx:
            if tx.execute("SELECT 1 FROM automations WHERE automation_id = ?", (automation_id,)).fetchone() is None:
                raise m.AutomationNotFound(automation_id)
            if tx.execute(f"SELECT 1 FROM runs WHERE automation_id = ? AND status IN ({marks})",
                          (automation_id, *m.LIVE_STATUSES)).fetchone():
                raise m.AutomationInvalid("already_running", automation_id)
            tx.execute("INSERT INTO runs (run_id, automation_id, trigger, status, boot_id, created_at, number, host) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (run_id, automation_id, trigger, m.CLAIMED, boot_id, now, next_number(tx, automation_id), this_label()))
        return self.run(run_id)

    def update_run(self, run_id: str, **fields: Any) -> Dict[str, Any]:
        unknown = set(fields) - _RUN_FIELDS
        if unknown:
            raise m.AutomationInvalid("field_unknown", ",".join(sorted(unknown)))
        sets: List[str] = []
        args: List[Any] = []
        for key, value in fields.items():
            if key == "error" and value is not None:
                value = redact(str(value))[:500]
            if key in JSON_RUN:
                text = None if value is None else json.dumps(value)
                if key == "report":
                    size = len(text.encode()) if text else 0
                    if size > m.REPORT_CAP_BYTES:
                        raise m.ReportTooLarge(run_id)
                    sets.append("report_bytes = ?")
                    args.append(size)
                    sets.append("output_empty = ?")
                    args.append(None if value is None or value == {"pruned": True} else int(report_is_empty(value)))
                value = text
            sets.append(f"{key} = ?")
            args.append(value)
        doomed: List[str] = []
        with self._write(topics.AUTOMATION_RUNS) as tx:
            if fields.get("status") not in (None, *m.LIVE_STATUSES) and "title" not in fields:
                self._add_title(tx, run_id, fields, sets, args)
            if sets and tx.execute(f"UPDATE runs SET {', '.join(sets)} WHERE run_id = ?", (*args, run_id)).rowcount == 0:
                raise m.AutomationNotFound(run_id)
            if fields.get("status") not in (None, *m.LIVE_STATUSES):
                doomed = self._prune(tx)
        attachments.remove(self.attachments_root, doomed)
        return self.run(run_id)

    @staticmethod
    def _add_title(tx: Tx, run_id: str, fields: Dict[str, Any], sets: List[str], args: List[Any]) -> None:
        row = tx.execute("SELECT r.reason, r.report, r.output_empty, a.name, a.target FROM runs r "
                         "JOIN automations a ON a.automation_id = r.automation_id WHERE r.run_id = ?", (run_id,)).fetchone()
        if row is None:
            return
        report = fields["report"] if "report" in fields else (json.loads(row["report"]) if row["report"] else None)
        empty = (None if report is None or report == {"pruned": True} else report_is_empty(report)) if "report" in fields \
            else (None if row["output_empty"] is None else bool(row["output_empty"]))
        title, summary = run_title.build(name=row["name"], status=fields["status"], kind=json.loads(row["target"]).get("kind"),
                                         reason=fields["reason"] if "reason" in fields else row["reason"], report=report,
                                         output_empty=empty)
        sets += ["title = ?", "summary = ?"]
        args += [title, summary]

    @property
    def attachments_root(self) -> Path:
        return self._storage.path / attachments.ROOT_NAME

    def run_ids(self) -> List[str]:
        with closing(self._read()) as conn:
            return [r["run_id"] for r in conn.execute("SELECT run_id FROM runs")]

    @staticmethod
    def _prune(tx: Tx) -> List[str]:
        over = ("SELECT seq FROM (SELECT seq, ROW_NUMBER() OVER (PARTITION BY automation_id ORDER BY seq DESC) AS n FROM runs) "
                "WHERE n > ?")
        doomed = [r["run_id"] for r in tx.execute(f"SELECT run_id FROM runs WHERE seq IN ({over})", (m.RUNS_KEPT,))]
        tx.execute(f"DELETE FROM runs WHERE seq IN ({over})", (m.RUNS_KEPT,))
        total = tx.execute("SELECT COALESCE(SUM(report_bytes), 0) FROM runs").fetchone()[0]
        if total <= m.REPORTS_TOTAL_CAP_BYTES:
            return doomed
        pruned = json.dumps({"pruned": True})
        for row in tx.execute("SELECT seq, report_bytes FROM runs WHERE report_bytes > ? ORDER BY seq", (len(pruned),)).fetchall():
            tx.execute("UPDATE runs SET report = ?, report_bytes = ? WHERE seq = ?", (pruned, len(pruned), row["seq"]))
            total -= row["report_bytes"] - len(pruned)
            if total <= m.REPORTS_TOTAL_CAP_BYTES:
                break
        return doomed

    def add_run_sessions(self, run_id: str, rows: List[Dict[str, Any]]) -> None:
        with self._write(nudge=False) as tx:
            for row in rows:
                tx.execute("INSERT OR IGNORE INTO run_sessions (run_id, session_uuid, session_row_id, member_index) VALUES (?,?,?,?)",
                           (run_id, row["session_uuid"], row.get("session_row_id"), row.get("member_index")))

    def active_run_sessions(self) -> List[Dict[str, Any]]:
        sql = ("SELECT rs.*, r.status AS run_status, r.started_at, r.automation_id, a.name AS automation_name, "
               "(SELECT COUNT(DISTINCT r2.run_id) FROM runs r2 JOIN run_sessions x ON x.run_id = r2.run_id "
               " WHERE r2.automation_id = r.automation_id AND r2.seq > r.seq) AS newer "
               "FROM run_sessions rs JOIN runs r ON r.run_id = rs.run_id JOIN automations a ON a.automation_id = r.automation_id "
               "WHERE rs.closed_at IS NULL ORDER BY r.seq, rs.member_index")
        with closing(self._read()) as conn:
            return [dict(r) for r in conn.execute(sql)]

    def run_session_rows(self, run_id: str) -> List[Dict[str, Any]]:
        with closing(self._read()) as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM run_sessions WHERE run_id = ? ORDER BY member_index", (run_id,))]

    def mark_run_session(self, run_id: str, session_uuid: str, *, slept: bool = False, closed: bool = False) -> None:
        now = self._clock()
        with self._write(nudge=False) as tx:
            if slept:
                tx.execute("UPDATE run_sessions SET slept_at = COALESCE(slept_at, ?) WHERE run_id = ? AND session_uuid = ?",
                           (now, run_id, session_uuid))
            if closed:
                tx.execute("UPDATE run_sessions SET closed_at = COALESCE(closed_at, ?) WHERE run_id = ? AND session_uuid = ?",
                           (now, run_id, session_uuid))

    def reconcile_boot(self, boot_id: str) -> List[Dict[str, Any]]:
        marks = ",".join("?" * len(m.LIVE_STATUSES))
        now = self._clock()
        with self._write() as tx:
            rows = tx.execute(f"SELECT * FROM runs WHERE status IN ({marks}) AND COALESCE(boot_id, '') != ?",
                              (*m.LIVE_STATUSES, boot_id)).fetchall()
            for row in rows:
                sets, args = ["status = ?", "reason = ?", "ended_at = ?", "child = NULL"], [m.FAILED, m.R_INTERRUPTED, now]
                self._add_title(tx, row["run_id"], {"status": m.FAILED, "reason": m.R_INTERRUPTED}, sets, args)
                tx.execute(f"UPDATE runs SET {', '.join(sets)} WHERE run_id = ?", (*args, row["run_id"]))
                tx.hit.add(topics.AUTOMATION_RUNS)
        return [run_row(r) for r in rows]

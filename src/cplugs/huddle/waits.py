
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

import structlog
from pydantic import BaseModel

from src.cplugs.huddle import rules, wait_checks
from src.cplugs.huddle.rules import TaskManagerInvalid

logger = structlog.get_logger()

INSTALL, SESSION, PERSON, VENDOR, OTHER = "install", "session", "person", "vendor", "other"
KINDS = (INSTALL, SESSION, PERSON, VENDOR, OTHER)
DEFAULT_EXPECT_S: Mapping[str, int] = {INSTALL: 3600, SESSION: 3 * 3600, PERSON: 24 * 3600, VENDOR: 24 * 3600}
GRACE_FRACTION = 0.5
MIN_GRACE_S = 15 * 60
MAX_EXPECT_S = 30 * 24 * 3600
OWNER_GRANT_S = 24 * 3600
MAX_ON, MAX_REASON = 200, 300
RECENT_PARK_WINDOW_S = 2 * 24 * 3600
MAX_RECENT_PARKS = 2
COUNTED = ("ended", "expired", "escalated")
ESCALATION_BACKSTOP_S = 24 * 3600
CHECK_BACKOFF_FIRST_S, CHECK_BACKOFF_MAX_S = 60.0, 1800.0
_OWNER_WORDS = re.compile(r"\b(joe|owner|contributor|the user|the human)\b", re.IGNORECASE)

ACTIVE, ESCALATED = "active", "escalated"
LIVE = (ACTIVE, ESCALATED)
EXPIRED, CLEARED, FAILED, SETTLED = "expired", "cleared", "failed", "settled"
SELECT_COL = ("(SELECT json_object('waiting_on', w.waiting_on, 'kind', w.kind, 'set_at', w.set_at, 'expect_by', w.expect_by, 'deadline', w.deadline, "
              "'extended', w.extended, 'extend_reason', w.extend_reason, 'check_kind', w.check_kind, 'check_result', w.check_result, "
              "'status', w.status, 'legacy', w.legacy) FROM work_item_waits w WHERE w.item_id = work_items.id AND w.legacy = 0 AND w.status IN ('active', 'escalated') "
              "ORDER BY w.id DESC LIMIT 1) AS wait_json")
FIELD = "wait"
TOKEN_KEY = "wait_token"
ARGS = ("waiting_on", "wait_kind", "expect_by", "wait_check", "extend_reason")


@dataclass(frozen=True)
class WaitSpec:

    waiting_on: str
    kind: str
    expect_by: float
    check: Optional[BaseModel] = None
    extend_reason: str = ""


def wire(row: Mapping[str, Any]) -> Dict[str, Any]:
    if "wait_json" not in row.keys() or not row["wait_json"]:
        return {}
    return {FIELD: json.loads(row["wait_json"])}


def deadline_for(set_at: float, expect_by: float) -> float:
    return expect_by + max(GRACE_FRACTION * (expect_by - set_at), MIN_GRACE_S)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_token() -> str:
    return secrets.token_urlsafe(32)


def parse_expect_by(value: object, now: float) -> float:
    if not isinstance(value, str) or not value.strip():
        raise TaskManagerInvalid("expect_by must be an ISO 8601 time with a UTC offset, e.g. 2026-10-13T20:00:00-04:00")
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise TaskManagerInvalid("expect_by must be an ISO 8601 time with a UTC offset, e.g. 2026-10-13T20:00:00-04:00") from None
    if parsed.tzinfo is None:
        raise TaskManagerInvalid("expect_by needs a UTC offset (a time with no offset means a different moment on each machine)")
    at = parsed.timestamp()
    if at <= now:
        raise TaskManagerInvalid("expect_by is in the past: say when this should really be over")
    if at > now + MAX_EXPECT_S:
        raise TaskManagerInvalid("expect_by is more than 30 days out: park it in todo, or ask the owner")
    return at


def names_owner(text: str) -> bool:
    return _OWNER_WORDS.search(text) is not None


def clean_spec(args: Mapping[str, Any], now: float, *, extending: bool = False) -> WaitSpec:
    on = rules.clean_text(args.get("waiting_on"), "waiting_on", MAX_ON) if args.get("waiting_on") else ""
    kind = args.get("wait_kind")
    if not on or kind not in KINDS:
        raise TaskManagerInvalid(f"a task goes to waiting only with waiting_on (what it waits on, short) and wait_kind ({', '.join(KINDS)}); "
                            "waiting on the owner is a question: use task_manager_ask (task_manager_guide topic: 31)")
    if kind in (PERSON, OTHER) and names_owner(on):
        raise TaskManagerInvalid("waiting on the owner is a question, not a wait: ask it with task_manager_ask (the owner answers in the Task Manager), "
                            "or set review when your part is done")
    if args.get("expect_by"):
        expect = parse_expect_by(args["expect_by"], now)
    elif kind in DEFAULT_EXPECT_S:
        expect = now + DEFAULT_EXPECT_S[kind]
    else:
        raise TaskManagerInvalid("expect_by is required for a wait of kind other: when should this be over? (ISO 8601 with a UTC offset)")
    reason = ""
    if extending:
        reason = rules.clean_text(args.get("extend_reason"), "extend_reason", MAX_REASON) if args.get("extend_reason") else ""
        if not reason:
            raise TaskManagerInvalid("your last wait on this task ran out and the task came back to you: to wait again (the one extension) "
                                "give extend_reason, why it is still blocked and what exactly it waits on; or clear it, or ask with task_manager_ask")
    check = wait_checks.parse(args["wait_check"]) if args.get("wait_check") else None
    return WaitSpec(on, str(kind), expect, check, reason)


def live(conn: sqlite3.Connection, item_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM work_item_waits WHERE item_id = ? AND status IN ('active', 'escalated') ORDER BY id DESC LIMIT 1", (item_id,)).fetchone()


def on_owner(conn: sqlite3.Connection, item_id: int) -> bool:
    wait = live(conn, item_id)
    return wait is not None and (names_owner(wait["waiting_on"]) or names_owner(wait["kind"]))


def recent_parks(conn: sqlite3.Connection, item_id: int, now: float) -> int:
    marks = ", ".join("?" for _ in COUNTED)
    return conn.execute(f"SELECT COUNT(*) FROM work_item_waits WHERE item_id = ? AND legacy = 0 AND set_at > ? AND status IN ({marks})",
                        (item_id, now - RECENT_PARK_WINDOW_S, *COUNTED)).fetchone()[0]


def _check_columns(spec: WaitSpec, now: float) -> Dict[str, Any]:
    if spec.check is None:
        return {"check_kind": "", "check_json": "", "check_next_at": None}
    kind = spec.check.kind  # type: ignore[attr-defined]
    return {"check_kind": kind, "check_json": spec.check.model_dump_json(),
            "check_next_at": None if kind in wait_checks.EVENT_KINDS else now}


def park_plan(conn: sqlite3.Connection, row: Mapping[str, Any], now: float) -> Dict[str, Any]:
    plan: Dict[str, Any] = {"extending": False, "in_place": None, "blocked": ""}
    if row["state"] == rules.WAITING:
        current = live(conn, row["id"])
        if current is not None and not current["legacy"]:
            if current["status"] == ESCALATED:
                plan["blocked"] = "the owner has been asked about this wait; it is their to answer (push, drop or wait longer)"
            elif current["extended"]:
                plan["blocked"] = "this wait was already extended once: clear it, finish what you can yourself, or ask the owner with task_manager_ask"
            else:
                plan["in_place"] = current
                plan["extending"] = True
            return plan
    recent = recent_parks(conn, row["id"], now)
    if recent >= MAX_RECENT_PARKS:
        plan["blocked"] = (f"this task was parked {recent} times in the last two days and each ran out or was undone: that is the one extension used. "
                           "Do your part yourself, or ask the owner with task_manager_ask")
    elif recent:
        plan["extending"] = True
    return plan


def begin(conn: sqlite3.Connection, item_id: int, spec: WaitSpec, *, set_by: str, now: float, in_place: Optional[sqlite3.Row] = None) -> Optional[str]:
    deadline = deadline_for(now, spec.expect_by)
    if in_place is not None:
        conn.execute("UPDATE work_item_waits SET waiting_on = ?, kind = ?, expect_by = ?, deadline = ?, extended = 1, extend_reason = ? WHERE id = ?",
                     (spec.waiting_on, spec.kind, spec.expect_by, deadline, spec.extend_reason, in_place["id"]))
        if spec.check is not None:
            cols = _check_columns(spec, now)
            conn.execute("UPDATE work_item_waits SET check_kind = ?, check_json = ?, check_next_at = ?, check_runs = 0, check_result = '' WHERE id = ?",
                         (cols["check_kind"], cols["check_json"], cols["check_next_at"], in_place["id"]))
        return None
    conn.execute("UPDATE work_item_waits SET status = 'replaced', token_hash = '', ended_at = ? WHERE item_id = ? AND status IN ('active', 'escalated')", (now, item_id))
    token = mint_token()
    cols = _check_columns(spec, now)
    conn.execute(
        "INSERT INTO work_item_waits (item_id, waiting_on, kind, set_by, set_at, expect_by, deadline, extended, extend_reason, check_kind, check_json, "
        "check_next_at, token_hash, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')",
        (item_id, spec.waiting_on, spec.kind, set_by, now, spec.expect_by, deadline, int(bool(spec.extend_reason)), spec.extend_reason,
         cols["check_kind"], cols["check_json"], cols["check_next_at"], hash_token(token)))
    return token


@dataclass(frozen=True)
class Park:

    spec: WaitSpec
    set_by: str
    in_place: Optional[sqlite3.Row] = None

    def commit(self, conn: sqlite3.Connection, item_id: int, now: float) -> Optional[str]:
        return begin(conn, item_id, self.spec, set_by=self.set_by, now=now, in_place=self.in_place)


def prepare_park(conn: sqlite3.Connection, row: Mapping[str, Any], args: Mapping[str, Any], set_by: str, now: float) -> Optional[Park]:
    given = any(args.get(name) for name in ARGS)
    plan = park_plan(conn, row, now)
    if row["state"] == rules.WAITING and not given:
        return None
    if plan["blocked"]:
        raise TaskManagerInvalid(plan["blocked"])
    spec = clean_spec(args, now, extending=plan["extending"])
    return Park(spec, set_by, plan["in_place"])


def check_token(row: Optional[Mapping[str, Any]], token: object) -> bool:
    if row is None or not row["token_hash"] or not isinstance(token, str) or not token:
        return False
    return hmac.compare_digest(row["token_hash"], hash_token(token))


def backoff_s(runs: int) -> float:
    return min(CHECK_BACKOFF_FIRST_S * (2 ** max(runs - 1, 0)), CHECK_BACKOFF_MAX_S)


class WaitStore:

    def __init__(self, store: Any) -> None:
        self._store = store

    def for_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        with closing(self._store._read_connection()) as conn:
            row = live(conn, item_id)
        return None if row is None else {k: row[k] for k in row.keys() if k != "token_hash"}

    def verify(self, item_id: int, token: object) -> Optional[Dict[str, Any]]:
        with closing(self._store._read_connection()) as conn:
            row = live(conn, item_id)
        if not check_token(row, token):
            return None
        return {k: row[k] for k in row.keys() if k != "token_hash"}

    def claim_end(self, wait_id: int, status: str, note: str) -> bool:
        with closing(self._store._connect(True)) as conn, conn:
            cur = conn.execute("UPDATE work_item_waits SET status = ?, token_hash = '', ended_at = ?, ended_note = ? WHERE id = ? AND status IN ('active', 'escalated')",
                               (status, self._store._clock(), note[:MAX_REASON], wait_id))
            return cur.rowcount == 1

    def due_expiries(self, now: float) -> List[Dict[str, Any]]:
        with closing(self._store._read_connection()) as conn:
            rows = conn.execute("SELECT w.* FROM work_item_waits w JOIN work_items i ON i.id = w.item_id WHERE w.status IN ('active', 'escalated') AND i.deleted = 0 "
                                "AND w.deadline <= ? ORDER BY w.deadline", (now,)).fetchall()
        return [{k: r[k] for k in r.keys() if k != "token_hash"} for r in rows]

    def claim_expiry(self, wait: Mapping[str, Any], now: float) -> str:
        status = ESCALATED if wait["extended"] else EXPIRED
        with closing(self._store._connect(True)) as conn, conn:
            cur = conn.execute("UPDATE work_item_waits SET status = ?, token_hash = CASE WHEN ? = 'expired' THEN '' ELSE token_hash END, ended_at = ?, "
                               "deadline = CASE WHEN ? = 'escalated' THEN ? ELSE deadline END "
                               "WHERE id = ? AND status = 'active' AND deadline <= ?",
                               (status, status, now if status == EXPIRED else None, status, now + ESCALATION_BACKSTOP_S, wait["id"], now))
            return status if cur.rowcount == 1 else ""

    def claim_backstop(self, wait: Mapping[str, Any], now: float) -> bool:
        with closing(self._store._connect(True)) as conn, conn:
            cur = conn.execute("UPDATE work_item_waits SET deadline = ? WHERE id = ? AND status = 'escalated' AND deadline <= ?",
                               (now + ESCALATION_BACKSTOP_S, wait["id"], now))
            return cur.rowcount == 1

    def has_open_question(self, item_id: int) -> bool:
        with closing(self._store._read_connection()) as conn:
            return conn.execute("SELECT 1 FROM work_messages WHERE item_id = ? AND kind = 'question' AND answered = 0 AND category = 'wait_stuck' LIMIT 1",
                                (item_id,)).fetchone() is not None

    def claim_due_checks(self, now: float, limit: int) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        with closing(self._store._connect(True)) as conn, conn:
            rows = conn.execute("SELECT w.* FROM work_item_waits w JOIN work_items i ON i.id = w.item_id WHERE w.status = 'active' AND i.deleted = 0 AND w.check_json != '' "
                                "AND w.check_next_at IS NOT NULL AND w.check_next_at <= ? ORDER BY w.check_next_at LIMIT ?", (now, limit)).fetchall()
            for row in rows:
                runs = row["check_runs"] + 1
                conn.execute("UPDATE work_item_waits SET check_runs = ?, check_last_at = ?, check_next_at = ? WHERE id = ?", (runs, now, now + backoff_s(runs), row["id"]))
                out.append({k: row[k] for k in row.keys() if k != "token_hash"})
        return out

    def record_result(self, wait_id: int, status: str) -> None:
        with closing(self._store._connect(True)) as conn, conn:
            conn.execute("UPDATE work_item_waits SET check_result = ? WHERE id = ?", (status, wait_id))

    def event_watchers(self) -> List[Dict[str, Any]]:
        marks = ", ".join("?" for _ in wait_checks.EVENT_KINDS)
        with closing(self._store._read_connection()) as conn:
            rows = conn.execute(f"SELECT * FROM work_item_waits WHERE status = 'active' AND check_kind IN ({marks})", wait_checks.EVENT_KINDS).fetchall()
        return [{k: r[k] for k in r.keys() if k != "token_hash"} for r in rows]

    def item_state(self, item_id: int) -> Optional[str]:
        with closing(self._store._read_connection()) as conn:
            row = conn.execute("SELECT state FROM work_items WHERE id = ? AND deleted = 0", (item_id,)).fetchone()
        return None if row is None else row["state"]

    def next_due(self, include_checks: bool = True) -> Optional[float]:
        with closing(self._store._read_connection()) as conn:
            row = conn.execute("SELECT MIN(deadline) AS d FROM work_item_waits WHERE status IN ('active', 'escalated')").fetchone()
            check = conn.execute("SELECT MIN(check_next_at) AS c FROM work_item_waits WHERE status = 'active' AND check_json != '' AND check_next_at IS NOT NULL").fetchone()
        times = [t for t in (row["d"], check["c"] if include_checks else None) if t is not None]
        return min(times) if times else None


def grant_longer(conn: sqlite3.Connection, item_id: int, now: float) -> None:
    row = conn.execute("SELECT id FROM work_item_waits WHERE item_id = ? AND status = 'escalated' ORDER BY id DESC LIMIT 1", (item_id,)).fetchone()
    if row is not None:
        expect = now + OWNER_GRANT_S
        conn.execute("UPDATE work_item_waits SET status = 'active', set_at = ?, expect_by = ?, deadline = ? WHERE id = ?", (now, expect, deadline_for(now, expect), row["id"]))


def settle(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("UPDATE work_item_waits SET status = 'settled', token_hash = '' WHERE item_id = ? AND status IN ('ended', 'expired', 'escalated')", (item_id,))


def end_for_deleted(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM work_item_waits WHERE item_id = ?", (item_id,))

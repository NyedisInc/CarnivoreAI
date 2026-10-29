
from __future__ import annotations

import json
import re
import sqlite3
import threading
from typing import Any, Dict, Mapping, Optional, Sequence, Set

import structlog

from src.cplugs.sdk.cards import CardRefused

logger = structlog.get_logger()

KICKS: Set[str] = set()
_kicks_lock = threading.Lock()

DEALING_STEP_KEY = "cards_dealing_step"
DEAL_STATES = ("waiting", "delivered", "answered", "no_dealer", "dealing_off", "gave_up")

_RESTART = ("answered", "no_dealer", "dealing_off", "gave_up")


def defaults() -> Dict[str, Any]:
    return {"dealing": None, "auto_done": False, "auto_validate": False, "reorder": "suggest", "pace": "normal",
            "updated_at": None, "updated_by": ""}


def rules(conn: sqlite3.Connection, list_key: str) -> Dict[str, Any]:
    row = conn.execute("SELECT dealing, auto_done, auto_validate, reorder, pace, updated_at, updated_by "
                       "FROM work_card_rules WHERE list_key = ?", (list_key,)).fetchone()
    if row is None:
        return defaults()
    return {"dealing": None if row["dealing"] is None else bool(row["dealing"]), "auto_done": bool(row["auto_done"]),
            "auto_validate": bool(row["auto_validate"]), "reorder": row["reorder"], "pace": row["pace"],
            "updated_at": row["updated_at"], "updated_by": row["updated_by"]}


def request_deal(conn: sqlite3.Connection, project_key: str, reason: str, card_id: Optional[int], now: float) -> None:
    if not project_key.isdigit():
        return
    row = conn.execute("SELECT state, reasons FROM work_card_deals WHERE project_key = ?", (project_key,)).fetchone()
    if row is None or row["state"] in _RESTART:
        conn.execute("INSERT OR REPLACE INTO work_card_deals (project_key, state, reasons, offered_ids, requested_at, attempts) "
                     "VALUES (?, 'waiting', ?, '[]', ?, 0)", (project_key, json.dumps([reason]), now))
    else:
        merged = list(json.loads(row["reasons"]))
        if reason not in merged:
            merged.append(reason)
            conn.execute("UPDATE work_card_deals SET reasons = ? WHERE project_key = ?", (json.dumps(merged), project_key))
    with _kicks_lock:
        KICKS.add(project_key)
    logger.info("card_deal_requested", project=project_key, reason=reason, card=card_id)


def deal_state(conn: sqlite3.Connection, project_key: str, state: str, now: float, *, offered: Sequence[int] = (),
               attempt: bool = False, only_from: Sequence[str] = ()) -> bool:
    if state not in DEAL_STATES:
        raise ValueError(f"unknown deal state {state!r}")
    sets, args = ["state = ?", "attempts = attempts + ?"], [state, int(attempt)]
    if state == "delivered" or (state == "waiting" and attempt):
        sets.append("delivered_at = ?")
        args.append(now)
    if state == "answered":
        sets.append("answered_at = ?")
        args.append(now)
    if offered:
        sets.append("offered_ids = ?")
        args.append(json.dumps(list(offered)))
    where = "project_key = ?"
    args.append(project_key)
    if only_from:
        where += f" AND state IN ({', '.join('?' * len(only_from))})"
        args.extend(only_from)
    changed = conn.execute(f"UPDATE work_card_deals SET {', '.join(sets)} WHERE {where}", args).rowcount > 0
    if changed:
        logger.info("card_deal_state", project=project_key, state=state, attempt=attempt)
    return changed


def dealing_step_done(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM work_meta WHERE k = ?", (DEALING_STEP_KEY,)).fetchone() is not None


def dealing_on(conn: sqlite3.Connection, list_key: str) -> bool:
    return list_key.isdigit() and dealing_step_done(conn) and rules(conn, list_key)["dealing"] is not False


def ensure_dealing_step(conn: sqlite3.Connection, project_keys: Sequence[str], now: float) -> bool:
    if dealing_step_done(conn):
        return False
    keys = {k for k in project_keys if k.isdigit()}
    keys.update(r[0] for r in conn.execute("SELECT DISTINCT list_key FROM work_items WHERE deleted = 0") if r[0].isdigit())
    for key in sorted(keys):
        conn.execute("INSERT INTO work_card_rules (list_key, dealing, updated_at, updated_by) VALUES (?, 0, ?, 'server') "
                     "ON CONFLICT(list_key) DO UPDATE SET dealing = 0, updated_at = excluded.updated_at, updated_by = 'server' "
                     "WHERE work_card_rules.dealing IS NULL", (key, now))
    conn.execute("INSERT INTO work_meta (k, v) VALUES (?, ?)", (DEALING_STEP_KEY, int(now)))
    logger.info("card_dealing_step", projects=sorted(keys))
    return True


def drain_kicks() -> Set[str]:
    with _kicks_lock:
        taken = set(KICKS)
        KICKS.clear()
    return taken


RULE_KEYS = ("dealing", "auto_done", "auto_validate", "reorder", "pace")
REORDER_MODES = ("suggest", "auto")
PACE_MODES = ("normal", "asap")


def set_rules(conn: sqlite3.Connection, list_key: str, changes: Mapping[str, Any], by: str, now: float) -> Dict[str, Any]:
    if not list_key.isdigit():
        raise CardRefused("bad_rules", "only a project queue has card rules")
    unknown = set(changes) - set(RULE_KEYS)
    if unknown:
        raise CardRefused("bad_rules", f"unknown rule {sorted(unknown)[0]}")
    before = rules(conn, list_key)
    after = dict(before)
    for key, value in changes.items():
        if key in ("dealing", "auto_done", "auto_validate"):
            if type(value) is not bool:
                raise CardRefused("bad_rules", f"{key} is true or false")
        elif key == "reorder" and value not in REORDER_MODES:
            raise CardRefused("bad_rules", f"reorder is one of {', '.join(REORDER_MODES)}")
        elif key == "pace" and value not in PACE_MODES:
            raise CardRefused("bad_rules", f"pace is one of {', '.join(PACE_MODES)}")
        after[key] = value
    conn.execute("INSERT INTO work_card_rules (list_key, dealing, auto_done, auto_validate, reorder, pace, updated_at, updated_by) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(list_key) DO UPDATE SET dealing = excluded.dealing, "
                 "auto_done = excluded.auto_done, auto_validate = excluded.auto_validate, reorder = excluded.reorder, "
                 "pace = excluded.pace, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                 (list_key, None if after["dealing"] is None else int(after["dealing"]), int(after["auto_done"]),
                  int(after["auto_validate"]), after["reorder"], after["pace"], now, by))
    if after["dealing"] is True and before["dealing"] is not True:
        request_deal(conn, list_key, "dealing_on", None, now)
    logger.info("card_rules_set", list=list_key, by=by, changes=sorted(changes))
    return rules(conn, list_key)


def add_suggestion(conn: sqlite3.Connection, *, list_key: str, card_id: int, before_id: Optional[int], agent_id: int,
                   reason: str, now: float) -> int:
    cur = conn.execute("INSERT INTO work_card_suggestions (list_key, card_id, before_id, by_agent, reason, at, state) "
                       "VALUES (?, ?, ?, ?, ?, ?, 'open')", (list_key, card_id, before_id, agent_id, reason, now))
    return int(cur.lastrowid)


def settle_suggestion(conn: sqlite3.Connection, suggestion_id: int, state: str, now: float) -> Dict[str, Any]:
    row = conn.execute("SELECT id, list_key, card_id, before_id, by_agent, reason, at, state FROM work_card_suggestions WHERE id = ?",
                       (suggestion_id,)).fetchone()
    if row is None:
        raise CardRefused("no_suggestion", "no such suggestion")
    if row["state"] != "open":
        raise CardRefused("stale", f"that suggestion was already {row['state']}")
    conn.execute("UPDATE work_card_suggestions SET state = ? WHERE id = ?", (state, suggestion_id))
    logger.info("card_suggestion_settled", suggestion=suggestion_id, state=state, at=now)
    return {**dict(row), "state": state}


GRANT_SCOPE = re.compile(r"^(company|project):[1-9][0-9]{0,9}$")
GRANT_MAX_SLOTS = 20
GRANT_REASON_MAX = 500


def set_grant(conn: sqlite3.Connection, scope: str, slots: Optional[int], by: str, reason: str, now: float) -> Dict[str, Any]:
    if not GRANT_SCOPE.match(scope or ""):
        raise CardRefused("bad_grant", "a grant's scope is company:<id> or project:<id>")
    if slots is not None and (type(slots) is not int or not 0 <= slots <= GRANT_MAX_SLOTS):
        raise CardRefused("bad_grant", f"slots is a whole number from 0 to {GRANT_MAX_SLOTS}, or null to remove the grant")
    why = (reason or "").strip()[:GRANT_REASON_MAX]
    if slots is None:
        conn.execute("DELETE FROM work_card_grants WHERE scope = ?", (scope,))
    else:
        conn.execute("INSERT INTO work_card_grants (scope, slots, set_by, set_at, reason) VALUES (?, ?, ?, ?, ?) ON CONFLICT(scope) DO UPDATE SET "
                     "slots = excluded.slots, set_by = excluded.set_by, set_at = excluded.set_at, reason = excluded.reason", (scope, slots, by, now, why))
    logger.info("card_grant_set", scope=scope, slots=slots, by=by)
    return {"scope": scope, "slots": slots, "set_by": by, "set_at": now, "reason": why}

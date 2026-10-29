
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.core.app_alerts import constants as K
from src.core.app_alerts import kinds
from src.core.notifications import types

_COLUMNS = ("id, dedupe_key, source, severity, title_key, params_json, detail_key, state, sticky, "
            "auto_resolve, first_seen, last_seen, count, resolved_at, dismissed_at, snoozed_until, "
            "actions_json")

EV_RAISED, EV_UPDATED, EV_RESOLVED, EV_NONE = "raised", "updated", "resolved", "none"


class AlertInputError(ValueError):
    pass


@dataclass(frozen=True)
class AlertSpec:

    key: str
    source: str
    severity: str
    title_key: str
    params: Mapping[str, Any] = field(default_factory=dict)
    detail_key: Optional[str] = None
    sticky: bool = False
    auto_resolve: bool = True
    actions: Sequence[Mapping[str, Any]] = ()


def iso(moment: Optional[datetime] = None) -> str:
    return (moment or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


_PLUGIN_SOURCE = re.compile(r"cplug\.[a-z][a-z0-9]{1,23}")


def validate(spec: AlertSpec) -> None:
    if not spec.key or not spec.source:
        raise AlertInputError("key and source are required")
    if spec.severity not in K.SEVERITIES:
        raise AlertInputError(f"severity must be one of {K.SEVERITIES}")
    extra = f"{spec.source}." if _PLUGIN_SOURCE.fullmatch(spec.source) else None
    for name in (spec.title_key, spec.detail_key):
        if name is not None and not name.startswith((K.KEY_PREFIX,) + ((extra,) if extra else ())):
            raise AlertInputError(f"strings are catalog keys under {K.KEY_PREFIX!r} (or the plugin's own cplug.<id>.)")
    for value in spec.params.values():
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise AlertInputError("params must be JSON scalars")
    for action in spec.actions:
        validate_action(action, extra_prefix=extra)


def validate_action(action: Mapping[str, Any], *, extra_prefix: Optional[str] = None) -> None:
    explain = "explain_key" in action
    link = "href" in action
    needed = {"id", "label_key", *(("explain_key", "actions") if explain else ("href",) if link else ("method", "route"))}
    if not needed <= set(action):
        raise AlertInputError("an action names id, label_key and either href, method and route, or explain_key and actions")
    prefixes = (K.KEY_PREFIX,) + ((extra_prefix,) if extra_prefix else ())
    if not str(action["label_key"]).startswith(prefixes):
        raise AlertInputError("an action label is a catalog key")
    if explain:
        if not str(action["explain_key"]).startswith(prefixes):
            raise AlertInputError("an explainer is a catalog key")
        for nested in action["actions"]:
            validate_action(nested, extra_prefix=extra_prefix)
    elif not str(action[("href" if link else "route")]).startswith("#" if link else "/"):
        raise AlertInputError("an action link is an in-app fragment and its route a path")


def to_dict(row: Sequence[Any]) -> Dict[str, Any]:
    (rid, key, source, severity, title_key, params, detail_key, state, sticky, auto_resolve,
     first_seen, last_seen, count, resolved_at, dismissed_at, snoozed_until, actions) = tuple(row)
    parsed = json.loads(params or "{}")
    who = kinds.describe(rid, key, source, severity, title_key, parsed, json.loads(actions or "[]"), detail_key)
    return {
        "notify_type": types.type_for_alert_key(key),
        "id": rid, "key": key, "source": source, "severity": severity, "title_key": title_key,
        "params": parsed, "state": state,
        "sticky": bool(sticky), "auto_resolve": bool(auto_resolve), "first_seen": first_seen,
        "last_seen": last_seen, "count": count, "resolved_at": resolved_at,
        "dismissed_at": dismissed_at, "snoozed_until": snoozed_until,
        **who,
    }


def _one(conn: sqlite3.Connection, where: str, args: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
    row = conn.execute(f"SELECT {_COLUMNS} FROM {K.TABLE} WHERE {where} ORDER BY id DESC LIMIT 1", args).fetchone()
    return to_dict(row) if row else None


def get(conn: sqlite3.Connection, alert_id: int) -> Optional[Dict[str, Any]]:
    return _one(conn, "id = ?", (alert_id,))


def _write(conn: sqlite3.Connection, sql: str, args: Tuple[Any, ...]) -> int:
    conn.execute("BEGIN IMMEDIATE")
    try:
        changed = conn.execute(sql, args).rowcount
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return changed


def raise_alert(conn: sqlite3.Connection, spec: AlertSpec, *,
                now: Optional[datetime] = None) -> Tuple[Dict[str, Any], str]:
    validate(spec)
    stamp = iso(now)
    params, actions = json.dumps(dict(spec.params), sort_keys=True), json.dumps([dict(a) for a in spec.actions])
    conn.execute("BEGIN IMMEDIATE")
    try:
        opened = ",".join("?" * len(K.OPEN_STATES))
        row = conn.execute(f"SELECT id FROM {K.TABLE} WHERE dedupe_key = ? AND state IN ({opened})",
                           (spec.key, *K.OPEN_STATES)).fetchone()
        event = EV_UPDATED
        if row is None:
            row = conn.execute(f"SELECT id FROM {K.TABLE} WHERE dedupe_key = ? AND state = ? AND auto_resolve = 1 "
                               "AND resolved_at IS NULL ORDER BY id DESC LIMIT 1",
                               (spec.key, K.STATE_DISMISSED)).fetchone()
            event = EV_NONE
        if row is None:
            rid = conn.execute(
                f"INSERT INTO {K.TABLE} (dedupe_key, source, severity, title_key, params_json, detail_key, "
                "state, sticky, auto_resolve, first_seen, last_seen, count, actions_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (spec.key, spec.source, spec.severity, spec.title_key, params, spec.detail_key,
                 K.STATE_ACTIVE, int(spec.sticky), int(spec.auto_resolve), stamp, stamp, actions)).lastrowid
            event = EV_RAISED
        else:
            rid = row[0]
            conn.execute(f"UPDATE {K.TABLE} SET count = count + 1, last_seen = ?, severity = ?, title_key = ?, "
                         "params_json = ?, detail_key = ?, actions_json = ? WHERE id = ?",
                         (stamp, spec.severity, spec.title_key, params, spec.detail_key, actions, rid))
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return get(conn, rid), event


def resolve(conn: sqlite3.Connection, key: str, *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    stamp = iso(now)
    opened = ",".join("?" * len(K.OPEN_STATES))
    conn.execute("BEGIN IMMEDIATE")
    try:
        ids = [r[0] for r in conn.execute(
            f"SELECT id FROM {K.TABLE} WHERE dedupe_key = ? AND state IN ({opened}) "
            "AND auto_resolve = 1 AND sticky = 0", (key, *K.OPEN_STATES)).fetchall()]
        for rid in ids:
            conn.execute(f"UPDATE {K.TABLE} SET state = ?, resolved_at = ?, snoozed_until = NULL "
                         f"WHERE id = ? AND state IN ({opened})", (K.STATE_RESOLVED, stamp, rid, *K.OPEN_STATES))
        conn.execute(f"UPDATE {K.TABLE} SET resolved_at = ? WHERE dedupe_key = ? AND state = ? "
                     "AND resolved_at IS NULL", (stamp, key, K.STATE_DISMISSED))
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return [get(conn, rid) for rid in ids]


def dismiss(conn: sqlite3.Connection, alert_id: int, *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    _write(conn, f"UPDATE {K.TABLE} SET state = ?, dismissed_at = ?, snoozed_until = NULL "
                 "WHERE id = ? AND state != ?", (K.STATE_DISMISSED, iso(now), alert_id, K.STATE_DISMISSED))
    return get(conn, alert_id)


def snooze(conn: sqlite3.Connection, alert_id: int, minutes: int, *,
           now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    until = iso((now or datetime.now(timezone.utc)) + timedelta(minutes=minutes))
    opened = ",".join("?" * len(K.OPEN_STATES))
    changed = _write(conn, f"UPDATE {K.TABLE} SET state = ?, snoozed_until = ? WHERE id = ? AND state IN ({opened})",
                     (K.STATE_SNOOZED, until, alert_id, *K.OPEN_STATES))
    return get(conn, alert_id) if changed else None


def wake_snoozed(conn: sqlite3.Connection, *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    stamp = iso(now)
    conn.execute("BEGIN IMMEDIATE")
    try:
        ids = [r[0] for r in conn.execute(f"SELECT id FROM {K.TABLE} WHERE state = ? AND snoozed_until <= ?",
                                          (K.STATE_SNOOZED, stamp)).fetchall()]
        for rid in ids:
            conn.execute(f"UPDATE {K.TABLE} SET state = ?, snoozed_until = NULL WHERE id = ? AND state = ?",
                         (K.STATE_ACTIVE, rid, K.STATE_SNOOZED))
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return [get(conn, rid) for rid in ids]


def dismiss_resolved(conn: sqlite3.Connection, *, now: Optional[datetime] = None) -> int:
    return _write(conn, f"UPDATE {K.TABLE} SET state = ?, dismissed_at = ? WHERE state = ?",
                  (K.STATE_DISMISSED, iso(now), K.STATE_RESOLVED))


def prune(conn: sqlite3.Connection, *, now: Optional[datetime] = None) -> int:
    cutoff = iso((now or datetime.now(timezone.utc)) - timedelta(days=K.RETENTION_DAYS))
    return _write(conn, f"DELETE FROM {K.TABLE} WHERE state IN (?, ?) "
                        "AND COALESCE(dismissed_at, resolved_at, last_seen) < ?",
                  (K.STATE_RESOLVED, K.STATE_DISMISSED, cutoff))


def list_alerts(conn: sqlite3.Connection, *, include_closed: bool, limit: int) -> List[Dict[str, Any]]:
    wanted = K.STATES if include_closed else K.OPEN_STATES
    marks = ",".join("?" * len(wanted))
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM {K.TABLE} WHERE state IN ({marks}) "
        "ORDER BY CASE WHEN state IN ('active', 'snoozed') THEN 0 ELSE 1 END, last_seen DESC, id DESC LIMIT ?",
        (*wanted, limit)).fetchall()
    return [to_dict(r) for r in rows]


def counts(conn: sqlite3.Connection) -> Dict[str, int]:
    out = {sev: 0 for sev in K.SEVERITIES}
    for severity, n in conn.execute(f"SELECT severity, COUNT(*) FROM {K.TABLE} WHERE state = ? GROUP BY severity",
                                    (K.STATE_ACTIVE,)).fetchall():
        out[severity] = n
    return out

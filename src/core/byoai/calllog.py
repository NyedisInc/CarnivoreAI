
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from src.core import resource_push
from src.core.byoai.contracts import ModelInfo
from src.core.resource_push import topics

SCHEMA_VERSION = 1

MAX_CALLS = 2000

CHANGE_NOTICE_SECONDS = 1.0

RANGES = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}

TOP_N = 5

MAX_ERROR = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, feature TEXT, capability TEXT NOT NULL, connection_id TEXT,
  preset TEXT, model TEXT, ok INTEGER NOT NULL, latency_ms INTEGER,
  input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, error TEXT
);
CREATE TABLE IF NOT EXISTS models (
  connection_id TEXT PRIMARY KEY, fetched_at REAL NOT NULL, payload TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class CallRecord:

    capability: str
    ok: bool
    feature: Optional[str] = None
    connection_id: Optional[str] = None
    preset: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    error: Optional[str] = None
    ts: float = 0.0


class CallLog:

    def __init__(self, state_dir: Path) -> None:
        self.db_path = Path(state_dir) / "byoai.db"

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            conn.close()
            raise RuntimeError(f"byoai.db is schema {version}, newer than this build ({SCHEMA_VERSION})")
        if version < SCHEMA_VERSION:
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        return conn

    def record(self, call: CallRecord) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO calls (ts, feature, capability, connection_id, preset, model, ok,"
                    " latency_ms, input_tokens, output_tokens, cost_usd, error)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (call.ts or time.time(), call.feature, call.capability, call.connection_id,
                     call.preset, call.model, int(call.ok), call.latency_ms, call.input_tokens,
                     call.output_tokens, call.cost_usd,
                     call.error[:MAX_ERROR] if call.error else None))
                conn.execute(
                    "DELETE FROM calls WHERE id <= (SELECT id FROM calls ORDER BY id DESC"
                    " LIMIT 1 OFFSET ?)", (MAX_CALLS,))
        finally:
            conn.close()
        resource_push.notify_coalesced(topics.AI_CALLS, "log", CHANGE_NOTICE_SECONDS)

    def recent(self, limit: int = 100) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM calls ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def _where(range_name: Optional[str], feature: Optional[str], connection_id: Optional[str],
               model: Optional[str], ok: Optional[bool], now: float) -> Tuple[str, list]:
        clauses: List[str] = []
        params: list = []
        if range_name in RANGES:
            clauses.append("ts >= ?")
            params.append(now - RANGES[range_name])
        for column, value in (("feature", feature), ("connection_id", connection_id), ("model", model)):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        if ok is not None:
            clauses.append("ok = ?")
            params.append(int(ok))
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def page(self, *, limit: int = 50, before: Optional[int] = None, after: Optional[int] = None,
             range_name: Optional[str] = None, feature: Optional[str] = None, connection_id: Optional[str] = None,
             model: Optional[str] = None, ok: Optional[bool] = None) -> dict:
        where, params = self._where(range_name, feature, connection_id, model, ok, time.time())
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM calls" + where, params).fetchone()[0]
            cond = where + (" AND " if where else " WHERE ")
            if after is not None:
                rows = conn.execute(f"SELECT * FROM calls{cond}id > ? ORDER BY id ASC LIMIT ?",
                                    params + [after, limit]).fetchall()[::-1]
            elif before is not None:
                rows = conn.execute(f"SELECT * FROM calls{cond}id < ? ORDER BY id DESC LIMIT ?",
                                    params + [before, limit]).fetchall()
            else:
                rows = conn.execute(f"SELECT * FROM calls{where} ORDER BY id DESC LIMIT ?", params + [limit]).fetchall()
            calls = [dict(r) for r in rows]
            latest = conn.execute("SELECT COALESCE(MAX(id),0) FROM calls").fetchone()[0]
            newer = older = 0
            if calls:
                newer = conn.execute(f"SELECT COUNT(*) FROM calls{cond}id > ?", params + [calls[0]["id"]]).fetchone()[0]
                older = total - newer - len(calls)
        finally:
            conn.close()
        return {"calls": calls, "total": total, "start": newer + 1 if calls else 0, "latest": latest,
                "next": calls[-1]["id"] if calls and older > 0 else None,
                "prev": calls[0]["id"] if calls and newer > 0 else None}

    def summary(self, range_name: str = "24h") -> dict:
        name = range_name if range_name in RANGES else "24h"
        where, params = self._where(name, None, None, None, None, time.time())
        conn = self._connect()
        try:
            head = conn.execute(
                "SELECT COUNT(*) AS calls, COALESCE(SUM(1-ok),0) AS errors, COALESCE(SUM(cost_usd),0) AS spend,"
                " COALESCE(SUM(input_tokens),0) AS tin, COALESCE(SUM(output_tokens),0) AS tout"
                " FROM calls" + where, params).fetchone()
            lat = (where + (" AND " if where else " WHERE ")) + "latency_ms IS NOT NULL"
            n = conn.execute("SELECT COUNT(*) FROM calls" + lat, params).fetchone()[0]

            def percentile(fraction: float) -> Optional[int]:
                if not n:
                    return None
                row = conn.execute("SELECT latency_ms FROM calls" + lat + " ORDER BY latency_ms LIMIT 1 OFFSET ?",
                                   params + [min(n - 1, int(n * fraction))]).fetchone()
                return row[0]

            def top(column: str) -> List[dict]:
                cond = (where + (" AND " if where else " WHERE ")) + f"{column} IS NOT NULL AND {column} != ''"
                return [{"key": r[0], "calls": r[1], "spend": r[2]} for r in conn.execute(
                    f"SELECT {column}, COUNT(*), COALESCE(SUM(cost_usd),0) AS s FROM calls{cond}"
                    f" GROUP BY {column} ORDER BY s DESC, COUNT(*) DESC LIMIT ?", params + [TOP_N]).fetchall()]

            def distinct(column: str) -> List[str]:
                return [r[0] for r in conn.execute(
                    f"SELECT DISTINCT {column} FROM calls WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}")]

            result = {"range": name, "calls": head["calls"], "errors": head["errors"], "spend": head["spend"],
                      "tokens_in": head["tin"], "tokens_out": head["tout"],
                      "median_ms": percentile(0.5), "p95_ms": percentile(0.95),
                      "by_feature": top("feature"), "by_model": top("model"),
                      "options": {"feature": distinct("feature"), "connection": distinct("connection_id"),
                                  "model": distinct("model")}}
        finally:
            conn.close()
        return result

    def put_models(self, connection_id: str, models: List[ModelInfo]) -> None:
        payload = json.dumps([asdict(m) for m in models])
        conn = self._connect()
        try:
            with conn:
                conn.execute("INSERT OR REPLACE INTO models (connection_id, fetched_at, payload)"
                             " VALUES (?,?,?)", (connection_id, time.time(), payload))
        finally:
            conn.close()

    def get_models(self, connection_id: str) -> Optional[Tuple[float, List[ModelInfo]]]:
        conn = self._connect()
        try:
            row = conn.execute("SELECT fetched_at, payload FROM models WHERE connection_id=?",
                               (connection_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        entries = json.loads(row["payload"])
        if entries and "context_length" not in entries[0]:
            return None
        models = [ModelInfo(id=m["id"], capabilities=tuple(m["capabilities"]), flags=tuple(m["flags"]),
                            label=m["label"], meta=m["meta"], context_length=m["context_length"],
                            price_in=m["price_in"], price_out=m["price_out"],
                            inputs=tuple(m["inputs"]), outputs=tuple(m["outputs"])) for m in entries]
        return row["fetched_at"], models

    def recent_models(self, connection_id: str, limit: int = 8) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT model, capability FROM calls WHERE connection_id=? AND ok=1 AND model IS NOT NULL AND model!=''"
                " GROUP BY model, capability ORDER BY MAX(id) DESC LIMIT ?", (connection_id, limit)).fetchall()
        finally:
            conn.close()
        return [{"model": r["model"], "capability": r["capability"]} for r in rows]

    def clear_models(self, connection_id: str) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute("DELETE FROM models WHERE connection_id=?", (connection_id,))
        finally:
            conn.close()

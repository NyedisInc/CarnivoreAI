
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.config import settings
from src.core.approvals.inbox import item_id
from src.core.notifications.card_contract import LIMITS

logger = structlog.get_logger()

HEADER_NAME = "X-Carnivore-Cap"
CAP_BYTES = 32
ASK_TTL_SECONDS = 24 * 3600
OTHER_TTL_SECONDS = 72 * 3600
MAX_CARD_BYTES = LIMITS["card_full_bytes"]
_SHAPE = re.compile(r"[A-Za-z0-9_-]{%d}" % LIMITS["cap"])

_SCHEMA = """
CREATE TABLE IF NOT EXISTS caps (
    cap_sha256 TEXT PRIMARY KEY, device_row_id TEXT NOT NULL, type_id TEXT NOT NULL, kind TEXT NOT NULL,
    target TEXT NOT NULL, actions TEXT NOT NULL, media_ids TEXT NOT NULL, card_json TEXT NOT NULL,
    created REAL NOT NULL, expires REAL NOT NULL, used_at REAL, used_action TEXT, result_json TEXT,
    ask_id TEXT, retired_at REAL
)"""
_ADDED_COLUMNS = ("ask_id TEXT", "retired_at REAL")


@dataclass(frozen=True)
class CapRecord:

    cap_sha256: str
    device_row_id: str
    type_id: str
    kind: str
    target: Dict[str, Any]
    actions: Dict[str, str]
    media_ids: List[str]
    card: Dict[str, Any]
    created: float
    expires: float
    used_at: Optional[float]
    used_action: Optional[str]
    result: Optional[Dict[str, Any]]
    ask_id: Optional[str] = None
    retired_at: Optional[float] = None


def ask_id_of(target: Dict[str, Any]) -> Optional[str]:
    if target.get("type") == "dialog" and target.get("session") and target.get("fingerprint"):
        return item_id(str(target["session"]), str(target["fingerprint"]))
    return None


def hash_cap(cap: str) -> str:
    return hashlib.sha256(cap.encode("ascii", "replace")).hexdigest()


def has_cap_shape(cap: Optional[str]) -> bool:
    return bool(cap) and _SHAPE.fullmatch(cap) is not None  # type: ignore[arg-type]


def db_path() -> Path:
    return Path(settings.get_state_dir()) / "notify_caps.db"


class CapStore:

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect(self) -> sqlite3.Connection:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            os.close(os.open(self._path, os.O_CREAT | os.O_WRONLY, 0o600))
        conn = sqlite3.connect(self._path, timeout=5)
        conn.execute(_SCHEMA)
        have = {row[1] for row in conn.execute("PRAGMA table_info(caps)")}
        for column in _ADDED_COLUMNS:
            if column.split()[0] not in have:
                conn.execute(f"ALTER TABLE caps ADD COLUMN {column}")
        return conn

    def mint(self, *, device_row_id: str, type_id: str, kind: str, target: Dict[str, Any], actions: Dict[str, str],
             media_ids: Optional[List[str]] = None, card: Optional[Dict[str, Any]] = None, ask: bool = False,
             now: Optional[float] = None) -> Tuple[str, float]:
        card_json = json.dumps(card or {}, separators=(",", ":"))
        if len(card_json.encode()) > MAX_CARD_BYTES:
            raise ValueError("card is larger than 64 KB")
        cap = base64.urlsafe_b64encode(secrets.token_bytes(CAP_BYTES)).rstrip(b"=").decode("ascii")
        stamp = time.time() if now is None else now
        expires = stamp + (ASK_TTL_SECONDS if ask else OTHER_TTL_SECONDS)
        digest = hash_cap(cap)
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM caps WHERE expires < ?", (stamp - 3600,))
            conn.execute("INSERT INTO caps (cap_sha256, device_row_id, type_id, kind, target, actions, media_ids, card_json,"
                         " created, expires, ask_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (digest, device_row_id, type_id, kind, json.dumps(target), json.dumps(actions),
                          json.dumps(media_ids or []), card_json, stamp, expires, ask_id_of(target)))
        logger.info("notify_cap_minted", cap=digest[:8], kind=kind, type_id=type_id, ask=ask)
        return cap, expires

    def find(self, cap: Optional[str]) -> Optional[CapRecord]:
        if not has_cap_shape(cap):
            return None
        digest = hash_cap(cap)  # type: ignore[arg-type]
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT cap_sha256, device_row_id, type_id, kind, target, actions, media_ids, card_json, created,"
                               " expires, used_at, used_action, result_json, ask_id, retired_at FROM caps WHERE cap_sha256 = ?", (digest,)).fetchone()
        if row is None or not hmac.compare_digest(row[0], digest):
            return None
        return CapRecord(row[0], row[1], row[2], row[3], json.loads(row[4]), json.loads(row[5]), json.loads(row[6]),
                         json.loads(row[7]), row[8], row[9], row[10], row[11], json.loads(row[12]) if row[12] else None, row[13], row[14])

    def retire_ask(self, ask_id: str, now: Optional[float] = None) -> int:
        with closing(self._connect()) as conn, conn:
            n = conn.execute("UPDATE caps SET retired_at = ? WHERE ask_id = ? AND used_at IS NULL AND retired_at IS NULL",
                             (time.time() if now is None else now, ask_id)).rowcount
        if n:
            logger.info("notify_caps_retired", count=n)
        return n

    def reserve(self, digest: str, action: str, now: Optional[float] = None) -> bool:
        with closing(self._connect()) as conn, conn:
            won = conn.execute("UPDATE caps SET used_at = ?, used_action = ? WHERE cap_sha256 = ? AND used_at IS NULL",
                               (time.time() if now is None else now, action, digest)).rowcount
        return won == 1

    def finish(self, digest: str, result: Dict[str, Any]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE caps SET result_json = ? WHERE cap_sha256 = ?", (json.dumps(result), digest))

    def release(self, digest: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE caps SET used_at = NULL, used_action = NULL WHERE cap_sha256 = ? AND result_json IS NULL", (digest,))


_STORE: Optional[CapStore] = None


def get_store() -> CapStore:
    global _STORE
    if _STORE is None or _STORE._path != db_path():
        _STORE = CapStore(db_path())
    return _STORE

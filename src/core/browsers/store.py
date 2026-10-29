
from __future__ import annotations

import os
import re
import secrets
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import structlog

logger = structlog.get_logger()

BROWSERS_DIRNAME = "browsers"

ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")

MAX_LABEL_LENGTH = 120


@dataclass(frozen=True)
class BrowserRow:

    id: str
    label: str
    last_url: str
    created_at: str
    updated_at: str


def new_id() -> str:
    return secrets.token_hex(8)


def is_valid_id(browser_id: str) -> bool:
    return bool(ID_PATTERN.fullmatch(browser_id or ""))


def browsers_root(state_dir: Path) -> Path:
    return Path(state_dir) / BROWSERS_DIRNAME


def profile_dir(state_dir: Path, browser_id: str) -> Path:
    if not is_valid_id(browser_id):
        raise ValueError("not a browser session id")
    return browsers_root(state_dir) / browser_id / "profile"


def make_profile_dir(state_dir: Path, browser_id: str) -> Path:
    path = profile_dir(state_dir, browser_id)
    for level in (browsers_root(state_dir), path.parent, path):
        level.mkdir(mode=0o700, exist_ok=True)
        os.chmod(level, 0o700)
    return path


def delete_profile(state_dir: Path, browser_id: str) -> None:
    folder = profile_dir(state_dir, browser_id).parent
    if folder.exists():
        shutil.rmtree(folder)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(record: sqlite3.Row | tuple) -> BrowserRow:
    return BrowserRow(*tuple(record))


_COLUMNS = "id, label, last_url, created_at, updated_at"


def insert(conn: sqlite3.Connection, browser_id: str, label: str, last_url: str) -> BrowserRow:
    now = _now()
    conn.execute(
        f"INSERT INTO browser_sessions ({_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
        (browser_id, label[:MAX_LABEL_LENGTH], last_url, now, now),
    )
    return BrowserRow(browser_id, label[:MAX_LABEL_LENGTH], last_url, now, now)


def get(conn: sqlite3.Connection, browser_id: str) -> Optional[BrowserRow]:
    found = conn.execute(
        f"SELECT {_COLUMNS} FROM browser_sessions WHERE id = ?", (browser_id,)
    ).fetchone()
    return _row(found) if found else None


def list_all(conn: sqlite3.Connection) -> List[BrowserRow]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM browser_sessions ORDER BY created_at, id"
    ).fetchall()
    return [_row(r) for r in rows]


def update(
    conn: sqlite3.Connection,
    browser_id: str,
    *,
    label: Optional[str] = None,
    last_url: Optional[str] = None,
) -> Optional[BrowserRow]:
    current = get(conn, browser_id)
    if current is None:
        return None
    new_label = current.label if label is None else label[:MAX_LABEL_LENGTH]
    new_url = current.last_url if last_url is None else last_url
    now = _now()
    conn.execute(
        "UPDATE browser_sessions SET label = ?, last_url = ?, updated_at = ? WHERE id = ?",
        (new_label, new_url, now, browser_id),
    )
    return BrowserRow(browser_id, new_label, new_url, current.created_at, now)


def delete(conn: sqlite3.Connection, browser_id: str) -> bool:
    return conn.execute(
        "DELETE FROM browser_sessions WHERE id = ?", (browser_id,)
    ).rowcount > 0

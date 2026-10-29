"""The app's own record of what it sent and what it checked, per computer (D10, #2469).

Two small tables in ``publish_sends.db`` under ``state_dir()`` (never ``config.json``): ONE ROW PER SEND
(submission id, the folder it came from, its hosted-compatible digest and per-file sha256 map, the hero source and
media submission id) and the newest :data:`MAX_CHECKS` LOCAL CHECKS per location (a refused check never makes a
send, so the send row alone could not hold it). Every call opens its own connection, so any thread may call.
A record that cannot be written is the caller's to log: it must never fail a check or a send that already happened.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_CHECKS = 20
MAX_SENDS = 200
SUMMARY_CHARS = 400
DB_NAME = "publish_sends.db"
IMAGE_DIR = "publish_images"
MAX_IMAGE_BYTES = 512 * 1024
IMAGE_SHA = re.compile(r"[0-9a-f]{64}")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sends (
    submission_id TEXT PRIMARY KEY, location_id TEXT NOT NULL, harness TEXT NOT NULL, kind TEXT NOT NULL,
    name TEXT NOT NULL, version TEXT NOT NULL, digest TEXT NOT NULL, files TEXT NOT NULL,
    hero TEXT NOT NULL DEFAULT '', media_submission_id TEXT NOT NULL DEFAULT '', sent_at TEXT NOT NULL,
    hero_sha TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS sends_location ON sends (location_id, sent_at);
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, location_id TEXT NOT NULL, version TEXT NOT NULL,
    ok INTEGER NOT NULL, at TEXT NOT NULL, summary TEXT NOT NULL,
    grade TEXT NOT NULL DEFAULT '', files INTEGER, bytes INTEGER,
    digest TEXT NOT NULL DEFAULT '', findings TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS checks_location ON checks (location_id, id);
"""


_CHECK_COLUMNS = (
    ("grade", "TEXT NOT NULL DEFAULT ''"), ("files", "INTEGER"), ("bytes", "INTEGER"),
    ("digest", "TEXT NOT NULL DEFAULT ''"), ("findings", "TEXT NOT NULL DEFAULT ''"),
)
_SEND_COLUMNS = (("hero_sha", "TEXT NOT NULL DEFAULT ''"),)
MAX_FINDINGS = 20
FINDING_PATH_CHARS = 300


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clean_findings(findings: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in findings or []:
        code, path = str(item.get("code", ""))[:64], str(item.get("path", ""))[:FINDING_PATH_CHARS]
        if code and path and len(out) < MAX_FINDINGS:
            out.append({"code": code, "path": path})
    return out


def _decode_findings(raw: Optional[str]) -> List[Dict[str, str]]:
    try:
        found = json.loads(raw) if raw else []
    except ValueError:
        return []
    return _clean_findings(found) if isinstance(found, list) else []


class PublishSends:
    """The send and check records under one state directory."""

    def __init__(self, state_dir: Path) -> None:
        self._path = Path(state_dir) / DB_NAME
        self._images = Path(state_dir) / IMAGE_DIR

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        have = {row["name"] for row in conn.execute("PRAGMA table_info(checks)")}
        for column, ddl in _CHECK_COLUMNS:
            if column not in have:
                conn.execute(f"ALTER TABLE checks ADD COLUMN {column} {ddl}")
        have = {row["name"] for row in conn.execute("PRAGMA table_info(sends)")}
        for column, ddl in _SEND_COLUMNS:
            if column not in have:
                conn.execute(f"ALTER TABLE sends ADD COLUMN {column} {ddl}")
        return conn

    def record_send(self, *, submission_id: str, location_id: str, harness: str, kind: str, name: str,
                    version: str, digest: str, files: Dict[str, str]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO sends (submission_id, location_id, harness, kind, name, version, digest, files, sent_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (submission_id, location_id, harness, kind, name, version, digest,
                 json.dumps(files, sort_keys=True), now_iso()),
            )
            conn.execute(
                "DELETE FROM sends WHERE submission_id NOT IN (SELECT submission_id FROM sends ORDER BY rowid DESC LIMIT ?)",
                (MAX_SENDS,),
            )

    def set_hero(self, *, kind: str, name: str, source: str, media_submission_id: str, image_sha: str = "") -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE sends SET hero=?, media_submission_id=?, hero_sha=? WHERE rowid = ("
                "SELECT rowid FROM sends WHERE kind=? AND name=? ORDER BY rowid DESC LIMIT 1)",
                (source, media_submission_id, image_sha, kind, name),
            )
            kept = {row["hero_sha"] for row in conn.execute("SELECT hero_sha FROM sends WHERE hero_sha != ''")}
        self._prune_images(kept)

    def save_image(self, data: bytes) -> str:
        if not data or len(data) > MAX_IMAGE_BYTES:
            return ""
        sha = hashlib.sha256(data).hexdigest()
        self._images.mkdir(parents=True, exist_ok=True)
        target = self._images / sha
        if not target.exists():
            temp = self._images / f".{sha}.tmp"
            temp.write_bytes(data)
            os.replace(temp, target)
        return sha

    def image_bytes(self, sha: str) -> Optional[bytes]:
        if not IMAGE_SHA.fullmatch(sha):
            return None
        target = self._images / sha
        try:
            if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_IMAGE_BYTES:
                return None
            return target.read_bytes()
        except OSError:
            return None

    def _prune_images(self, kept: set) -> None:
        try:
            for entry in self._images.iterdir():
                if IMAGE_SHA.fullmatch(entry.name) and entry.name not in kept:
                    entry.unlink()
        except OSError:
            return

    def record_check(self, *, location_id: str, version: str, ok: bool, summary: str, grade: str = "",
                     files: Optional[int] = None, bytes: Optional[int] = None, digest: str = "",
                     findings: Optional[List[Dict[str, str]]] = None) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO checks (location_id, version, ok, at, summary, grade, files, bytes, digest, findings)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (location_id, version, 1 if ok else 0, now_iso(), summary[:SUMMARY_CHARS], grade[:4], files, bytes,
                 digest[:128], json.dumps(_clean_findings(findings))),
            )
            conn.execute(
                "DELETE FROM checks WHERE location_id=? AND id NOT IN ("
                "SELECT id FROM checks WHERE location_id=? ORDER BY id DESC LIMIT ?)",
                (location_id, location_id, MAX_CHECKS),
            )

    @staticmethod
    def _send(row: sqlite3.Row) -> Dict[str, Any]:
        out = dict(row)
        out["files"] = json.loads(out["files"])
        return out

    def sends_for(self, location_id: str) -> List[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM sends WHERE location_id=? ORDER BY rowid DESC", (location_id,)).fetchall()
        return [self._send(r) for r in rows]

    def latest_send(self, location_id: str) -> Optional[Dict[str, Any]]:
        found = self.sends_for(location_id)
        return found[0] if found else None

    def checks_for(self, location_id: str) -> List[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT version, ok, at, summary, grade, files, bytes, digest, findings FROM checks WHERE location_id=? ORDER BY id DESC",
                (location_id,),
            ).fetchall()
        return [{"version": r["version"], "ok": bool(r["ok"]), "at": r["at"], "summary": r["summary"],
                 "grade": r["grade"], "files": r["files"], "bytes": r["bytes"], "digest": r["digest"] or "",
                 "findings": _decode_findings(r["findings"])} for r in rows]

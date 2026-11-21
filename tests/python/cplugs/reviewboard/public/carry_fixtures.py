
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict

from src.plugins.reviewboard.public import links, responses

LINK_TABLES = ("links", "link_revisions")
RESPONSE_TABLES = ("responses", "visitors", "drafts", "board_numbers")


def _ladder(path: Path, steps: tuple) -> None:
    with closing(sqlite3.connect(path)) as conn, conn:
        for number, sql in enumerate(steps):
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version = {number + 1}")


def make_old_folder(folder: Path) -> Path:
    folder.mkdir(parents=True)
    links_db, responses_db = folder / "links.db", folder / "responses.db"
    _ladder(links_db, links.MIGRATIONS)
    _ladder(responses_db, responses.MIGRATIONS)
    with closing(sqlite3.connect(links_db)) as conn, conn:
        for n, (board, revoked, token) in enumerate([("kitchen", None, "pbl_a1.sec1"), ("kitchen", 1_700_000_500, None), ("garage", None, "pbl_a3.sec3")]):
            conn.execute("INSERT INTO links (id, secret_hash, board, revision, mode, created_at, expires_at, revoked_at, content_sha256, access, theme, token) "
                         "VALUES (?, ?, ?, 'r1', 'follow', 1700000000, 1700600000, ?, 'abc', 'answer', NULL, ?)", (f"a{n + 1}", f"hash{n}", board, revoked, token))
            conn.execute("INSERT INTO link_revisions (link_id, revision) VALUES (?, 'r1')", (f"a{n + 1}",))
    with closing(sqlite3.connect(responses_db)) as conn, conn:
        conn.execute("INSERT INTO visitors (board, link_id, key_hash, number, created_at) VALUES ('kitchen', 'a1', 'k1', 1, 1700000100), ('kitchen', 'a1', 'k2', 2, 1700000200)")
        conn.execute("INSERT INTO drafts (visitor, revision, body, updated_at, sent_at) VALUES (1, 'r1', '{}', 1700000300, NULL), (2, 'r1', '{}', 1700000400, 1700000450)")
        conn.execute("INSERT INTO responses (link_id, board, revision, kind, name, body, client_post_id, created_at, forwarded_at, visitor) "
                     "VALUES ('a1', 'kitchen', 'r1', 'comment', 'Sam', '{\"text\": \"hi\"}', 'p1', 1700000500, NULL, 1)")
        conn.execute("INSERT INTO board_numbers (board, last) VALUES ('kitchen', 2)")
    return folder


def counts(folder: Path) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for db, tables in (("links.db", LINK_TABLES), ("responses.db", RESPONSE_TABLES)):
        with closing(sqlite3.connect(folder / db)) as conn:
            out[f"{db}:user_version"] = conn.execute("PRAGMA user_version").fetchone()[0]
            for table in tables:
                out[f"{db}:{table}"] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return out


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

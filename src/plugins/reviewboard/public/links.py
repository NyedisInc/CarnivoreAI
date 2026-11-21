
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Literal, Optional, get_args

import structlog

from src.plugins.reviewboard.public.theme import dumps as theme_dumps, loads as theme_loads
from src.plugins.sdk import CplugStorage

logger = structlog.get_logger()

MIGRATIONS = (
    """
    CREATE TABLE links (
        id          TEXT PRIMARY KEY,
        secret_hash TEXT NOT NULL,
        board       TEXT NOT NULL,
        revision    TEXT NOT NULL,
        mode        TEXT NOT NULL CHECK (mode IN ('pinned', 'follow')),
        created_at  INTEGER NOT NULL,
        expires_at  INTEGER NOT NULL,
        revoked_at  INTEGER,
        content_sha256 TEXT NOT NULL
    );
    CREATE INDEX links_board ON links (board);
    """,
    """
    ALTER TABLE links ADD COLUMN access TEXT NOT NULL DEFAULT 'answer' CHECK (access IN ('answer', 'read'));
    ALTER TABLE links ADD COLUMN theme TEXT;
    CREATE TABLE link_revisions (
        link_id  TEXT NOT NULL,
        revision TEXT NOT NULL,
        PRIMARY KEY (link_id, revision)
    );
    INSERT INTO link_revisions (link_id, revision) SELECT id, revision FROM links;
    """,
    """
    ALTER TABLE links ADD COLUMN token TEXT;
    """,
)

Ttl = Literal["1h", "1d", "7d"]
Mode = Literal["pinned", "follow"]
Access = Literal["answer", "read"]
ACCESSES = get_args(Access)
TTL_SECONDS: Dict[Ttl, int] = {"1h": 3600, "1d": 86400, "7d": 7 * 86400}
MODES = get_args(Mode)
TOKEN_PREFIX = "pbl_"
_ID_BYTES, _SECRET_BYTES = 16, 32
_TOKEN = re.compile(r"pbl_([A-Za-z0-9_-]{22})\.([A-Za-z0-9_-]{43})")
_DUMMY_HASH = hashlib.sha256(b"publicboard-no-such-link").hexdigest()

CheckState = Literal["ok", "invalid", "ended"]


@dataclass(frozen=True)
class Link:

    id: str
    board: str
    revision: str
    mode: str
    created_at: int
    expires_at: int
    revoked_at: Optional[int]
    status: str
    content_sha256: str = ""
    access: str = "answer"
    theme: Optional[Dict[str, str]] = None
    copyable: bool = False

    @property
    def writable(self) -> bool:
        return self.access == "answer"

    def as_wire(self) -> Dict[str, Any]:
        return {"id": self.id, "board": self.board, "revision": self.revision, "mode": self.mode, "access": self.access, "created_at": self.created_at,
                "expires_at": self.expires_at, "revoked_at": self.revoked_at, "status": self.status, "copyable": self.copyable}


@dataclass(frozen=True)
class LinkCheck:

    state: CheckState
    link: Optional[Link] = None


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii", "ignore")).hexdigest()


def _status(expires_at: int, revoked_at: Optional[int], now: float) -> str:
    if revoked_at is not None:
        return "revoked"
    return "expired" if now >= expires_at else "active"


def _link(row: sqlite3.Row, now: float) -> Link:
    return Link(row["id"], row["board"], row["revision"], row["mode"], row["created_at"], row["expires_at"], row["revoked_at"],
                _status(row["expires_at"], row["revoked_at"], now), row["content_sha256"], row["access"], theme_loads(row["theme"]), row["token"] is not None)


@contextmanager
def _writer(storage: CplugStorage) -> Iterator[sqlite3.Connection]:
    with closing(storage.connect(True)) as conn, conn:
        yield conn


def content_hash(texts: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for text in texts:
        data = text.encode("utf-8", errors="replace")
        digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def content_matches(link: Link, texts: Iterable[str]) -> bool:
    return hmac.compare_digest(content_hash(texts).encode("ascii"), link.content_sha256.encode("ascii", "ignore"))


def mint(storage: CplugStorage, board: str, revision: str, ttl: str, mode: str, content_sha256: str, now: Optional[float] = None, *,
         access: str = "answer", theme: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    if ttl not in TTL_SECONDS:
        raise ValueError(f"ttl must be one of {', '.join(TTL_SECONDS)}")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    if access not in ACCESSES:
        raise ValueError(f"access must be one of {', '.join(ACCESSES)}")
    stamp = int(time.time() if now is None else now)
    _sweep_quietly(storage, stamp)
    link_id, secret = secrets.token_urlsafe(_ID_BYTES), secrets.token_urlsafe(_SECRET_BYTES)
    with _writer(storage) as conn:
        conn.execute("INSERT INTO links (id, secret_hash, board, revision, mode, created_at, expires_at, content_sha256, access, theme, token) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (link_id, _hash(secret), board, revision, mode, stamp, stamp + TTL_SECONDS[ttl], content_sha256, access, theme_dumps(theme),
                      f"{TOKEN_PREFIX}{link_id}.{secret}"))
        conn.execute("INSERT INTO link_revisions (link_id, revision) VALUES (?, ?)", (link_id, revision))
    logger.info("publicboard_link_minted", link=link_id, board=board, revision=revision, mode=mode, ttl=ttl, access=access, themed=theme is not None)
    link = Link(link_id, board, revision, mode, stamp, stamp + TTL_SECONDS[ttl], None, "active", content_sha256, access, theme, True)
    return {"token": f"{TOKEN_PREFIX}{link_id}.{secret}", "link": link}


def _sweep_quietly(storage: CplugStorage, now: float, link_id: Optional[str] = None) -> None:
    try:
        sweep_ended(storage, now)
    except sqlite3.Error as exc:
        logger.warning("publicboard_token_sweep_failed", link=link_id, error=type(exc).__name__)


def token_of(storage: CplugStorage, link_id: str, now: Optional[float] = None) -> Optional[str]:
    stamp = int(time.time() if now is None else now)
    with closing(storage.connect(False)) as conn:
        row = conn.execute("SELECT token FROM links WHERE id = ? AND revoked_at IS NULL AND expires_at > ?", (link_id, stamp)).fetchone()
    return None if row is None else row[0]


def check(storage: CplugStorage, token: str, now: Optional[float] = None) -> LinkCheck:
    parsed = _TOKEN.fullmatch(token or "")
    link_id, secret = parsed.groups() if parsed else ("", "")
    row = None
    if parsed:
        with closing(storage.connect(False)) as conn:
            row = conn.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    expected = row["secret_hash"] if row is not None else _DUMMY_HASH
    matches = hmac.compare_digest(_hash(secret).encode("ascii"), expected.encode("ascii"))
    if row is None or not matches:
        return LinkCheck("invalid")
    link = _link(row, time.time() if now is None else now)
    if link.status == "active":
        return LinkCheck("ok", link)
    if link.copyable:
        _sweep_quietly(storage, time.time() if now is None else now, link_id)
    return LinkCheck("ended")


def active(storage: CplugStorage, link_id: str, now: Optional[float] = None) -> Optional[Link]:
    with closing(storage.connect(False)) as conn:
        row = conn.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    link = _link(row, time.time() if now is None else now) if row is not None else None
    return link if link is not None and link.status == "active" else None


def advance(storage: CplugStorage, link_id: str, revision: str, content_sha256: str) -> int:
    with _writer(storage) as conn:
        count = conn.execute("UPDATE links SET revision = ?, content_sha256 = ? WHERE id = ? AND mode = 'follow' AND revoked_at IS NULL",
                             (revision, content_sha256, link_id)).rowcount
        if count:
            conn.execute("INSERT OR IGNORE INTO link_revisions (link_id, revision) VALUES (?, ?)", (link_id, revision))
    if count:
        logger.info("publicboard_link_advanced", link=link_id, revision=revision)
    return count


def served(storage: CplugStorage, link_id: str, revision: str) -> bool:
    with closing(storage.connect(False)) as conn:
        return conn.execute("SELECT 1 FROM link_revisions WHERE link_id = ? AND revision = ?", (link_id, revision)).fetchone() is not None


def served_revisions(storage: CplugStorage, link_id: str) -> List[str]:
    with closing(storage.connect(False)) as conn:
        rows = [str(r[0]) for r in conn.execute("SELECT revision FROM link_revisions WHERE link_id = ?", (link_id,))]
    return sorted(rows, key=lambda rev: int(rev[1:]) if rev[1:].isdigit() else 0)


def list_links(storage: CplugStorage, board: Optional[str] = None, now: Optional[float] = None) -> List[Link]:
    stamp = time.time() if now is None else now
    sql, args = ("SELECT * FROM links WHERE board = ? ORDER BY created_at DESC, id", (board,)) if board else ("SELECT * FROM links ORDER BY created_at DESC, id", ())
    with closing(storage.connect(False)) as conn:
        return [_link(row, stamp) for row in conn.execute(sql, args)]


def _revoke(storage: CplugStorage, where: str, args: tuple, now: Optional[float]) -> int:
    stamp = int(time.time() if now is None else now)
    with _writer(storage) as conn:
        count = conn.execute(f"UPDATE links SET revoked_at = ?, token = NULL WHERE revoked_at IS NULL AND {where}", (stamp, *args)).rowcount  # noqa: S608
    return count


def sweep_ended(storage: CplugStorage, now: Optional[float] = None) -> int:
    stamp = int(time.time() if now is None else now)
    with _writer(storage) as conn:
        return conn.execute("UPDATE links SET token = NULL WHERE token IS NOT NULL AND expires_at <= ?", (stamp,)).rowcount


def revoke_link(storage: CplugStorage, link_id: str, now: Optional[float] = None) -> int:
    count = _revoke(storage, "id = ?", (link_id,), now)
    if count:
        logger.info("publicboard_link_revoked", scope="link", link=link_id)
    return count


def revoke_board(storage: CplugStorage, board: str, now: Optional[float] = None) -> int:
    count = _revoke(storage, "board = ?", (board,), now)
    logger.info("publicboard_link_revoked", scope="board", board=board, count=count)
    return count


def clear_ended(storage: CplugStorage, board: str, now: Optional[float] = None) -> int:
    stamp = int(time.time() if now is None else now)
    with _writer(storage) as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM links WHERE board = ? AND (revoked_at IS NOT NULL OR expires_at <= ?)", (board, stamp))]
        for link_id in ids:
            conn.execute("DELETE FROM link_revisions WHERE link_id = ?", (link_id,))
            conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
    logger.info("publicboard_links_cleared", board=board, count=len(ids))
    return len(ids)


def revoke_all(storage: CplugStorage, now: Optional[float] = None) -> int:
    count = _revoke(storage, "1 = 1", (), now)
    logger.info("publicboard_link_revoked", scope="all", count=count)
    return count

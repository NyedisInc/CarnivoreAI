
from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import aiosqlite
import structlog

from src.core.relay_e2ee import derive_link_keys

logger = structlog.get_logger()


TOKEN_BYTES = 32

DEFAULT_TTL_SECONDS = 3600

MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 86400

MAX_LABEL_LENGTH = 80

PURGE_GRACE_SECONDS = 86400

LINK_TOKEN_DB_FILENAME = "spectator_link_tokens.db"


class LinkKeysUnavailableError(RuntimeError):
    pass


def link_token_db_path(db_path: str) -> Path:
    return Path(db_path).expanduser().parent / LINK_TOKEN_DB_FILENAME


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SpectatorLink:

    id: str
    session_id: str
    label: Optional[str]
    created_at: int
    expires_at: int
    revoked_at: Optional[int]
    last_connected_at: Optional[int]
    connect_count: int
    e2ee: bool = False

    def is_live(self, now: Optional[int] = None) -> bool:
        moment = int(time.time()) if now is None else int(now)
        if self.revoked_at is not None:
            return False
        return self.expires_at > moment


@dataclass(frozen=True)
class MintedLink:

    link: SpectatorLink
    token: str
    replaced: tuple[str, ...] = ()


def _row_to_link(row) -> SpectatorLink:
    return SpectatorLink(
        id=row[0],
        session_id=row[1],
        label=row[2],
        created_at=int(row[3]),
        expires_at=int(row[4]),
        revoked_at=None if row[5] is None else int(row[5]),
        last_connected_at=None if row[6] is None else int(row[6]),
        connect_count=int(row[7] or 0),
        e2ee=row[8] is not None,
    )


_COLUMNS = (
    "id, session_id, label, created_at, expires_at, revoked_at, "
    "last_connected_at, connect_count, link_nonce"
)


class SpectatorLinksStore:

    def __init__(self, db_path: str, *, token_db_path: Optional[str] = None):
        self._db_path = str(Path(db_path).expanduser())
        self._token_db_path = str(
            Path(token_db_path).expanduser() if token_db_path
            else link_token_db_path(self._db_path)
        )
        self._conn: Optional[aiosqlite.Connection] = None
        self._tokens: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spectator_links (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                token_sha256 TEXT NOT NULL UNIQUE,
                label TEXT,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked_at INTEGER,
                last_connected_at INTEGER,
                connect_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cur = await self._conn.execute("PRAGMA table_info(spectator_links)")
        columns = {str(row[1]) for row in await cur.fetchall()}
        await cur.close()
        if "link_nonce" not in columns:
            await self._conn.execute(
                "ALTER TABLE spectator_links ADD COLUMN link_nonce TEXT")
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_spectator_links_session "
            "ON spectator_links(session_id)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_spectator_links_expires "
            "ON spectator_links(expires_at)"
        )
        await self._conn.commit()
        try:
            Path(self._db_path).chmod(0o600)
        except OSError as exc:
            logger.warning(
                "spectator_links_chmod_failed", db=self._db_path, err=str(exc)
            )
        await self._init_token_sidecar()
        logger.info("spectator_links_store_initialized", db=self._db_path)

    async def _init_token_sidecar(self) -> None:
        path = Path(self._token_db_path)
        try:
            os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
            path.chmod(0o600)
        except OSError as exc:
            logger.warning(
                "spectator_link_tokens_chmod_failed", db=str(path), err=str(exc)
            )
        conn: Optional[aiosqlite.Connection] = None
        try:
            conn = await aiosqlite.connect(str(path))
            await conn.execute("PRAGMA journal_mode=DELETE")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS spectator_link_tokens (
                    link_id TEXT PRIMARY KEY,
                    token TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            cur = await conn.execute("PRAGMA table_info(spectator_link_tokens)")
            columns = {str(row[1]) for row in await cur.fetchall()}
            await cur.close()
            if "content_key" not in columns:
                await conn.execute(
                    "ALTER TABLE spectator_link_tokens ADD COLUMN content_key BLOB")
            await conn.commit()
        except (sqlite3.Error, OSError) as exc:
            logger.error(
                "spectator_link_tokens_unavailable", db=str(path), err=str(exc)
            )
            if conn is not None:
                await conn.close()
            return
        self._tokens = conn
        async with self._lock:
            await self._sweep_expired_tokens(int(time.time()))
            await self._revoke_keyless_v2_links()

    async def _revoke_keyless_v2_links(self) -> None:
        assert self._conn is not None and self._tokens is not None
        now = int(time.time())
        try:
            cur = await self._tokens.execute(
                "SELECT link_id FROM spectator_link_tokens WHERE content_key IS NOT NULL")
            keyed = {str(row[0]) for row in await cur.fetchall()}
            await cur.close()
        except sqlite3.Error as exc:
            logger.error("spectator_link_keys_unreadable", err=str(exc))
            return
        cur = await self._conn.execute(
            "SELECT id FROM spectator_links WHERE link_nonce IS NOT NULL "
            "AND revoked_at IS NULL AND expires_at > ?", (now,))
        stale = [str(row[0]) for row in await cur.fetchall() if str(row[0]) not in keyed]
        await cur.close()
        if not stale:
            return
        marks = ",".join("?" for _ in stale)
        await self._conn.execute(
            f"UPDATE spectator_links SET revoked_at = ? WHERE id IN ({marks})",
            (now, *stale))
        await self._conn.commit()
        await self._forget_tokens(stale)
        logger.info("spectator_links_revoked_pre_e2ee", revoked=len(stale))

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None
            if self._tokens is not None:
                await self._tokens.close()
                self._tokens = None

    async def _delete_tokens(self, where: str, params: tuple) -> None:
        if self._tokens is None:
            return
        try:
            cur = await self._tokens.execute(
                f"DELETE FROM spectator_link_tokens WHERE {where}", params
            )
            deleted = cur.rowcount or 0
            await cur.close()
            await self._tokens.commit()
            if deleted:
                await self._tokens.execute("VACUUM")
        except sqlite3.Error as exc:
            logger.error("spectator_link_tokens_delete_failed", err=str(exc))

    async def _forget_tokens(self, link_ids: Iterable[str]) -> None:
        ids = tuple(link_ids)
        if ids:
            marks = ",".join("?" for _ in ids)
            await self._delete_tokens(f"link_id IN ({marks})", ids)

    async def _sweep_expired_tokens(self, now: int) -> None:
        await self._delete_tokens("expires_at <= ?", (now,))

    async def mint(
        self,
        session_id: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        label: Optional[str] = None,
        identity: Optional[Tuple[str, str]] = None,
    ) -> MintedLink:
        assert self._conn is not None, "SpectatorLinksStore.init() not called"
        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = int(time.time())
        stored_label = label[:MAX_LABEL_LENGTH] if label else None
        link_id, nonce = identity if identity is not None else (uuid.uuid4().hex, None)
        keys = derive_link_keys(token, link_id) if nonce is not None else None
        if keys is not None and self._tokens is None:
            raise LinkKeysUnavailableError("the link key sidecar is unavailable")
        link = SpectatorLink(
            id=link_id,
            session_id=session_id,
            label=stored_label,
            created_at=now,
            expires_at=now + int(ttl_seconds),
            revoked_at=None,
            last_connected_at=None,
            connect_count=0,
            e2ee=keys is not None,
        )
        async with self._lock:
            if keys is not None and not await self._keep_token(link, token, keys.content_key):
                raise LinkKeysUnavailableError("the link key could not be kept")
            try:
                cur = await self._conn.execute(
                    "SELECT id FROM spectator_links "
                    "WHERE session_id = ? AND revoked_at IS NULL AND expires_at > ?",
                    (session_id, now),
                )
                rows = await cur.fetchall()
                await cur.close()
                replaced = tuple(str(row[0]) for row in rows)
                if replaced:
                    placeholders = ",".join("?" for _ in replaced)
                    await self._conn.execute(
                        "UPDATE spectator_links SET revoked_at = ? "
                        f"WHERE id IN ({placeholders})",
                        (now, *replaced),
                    )
                await self._conn.execute(
                    "INSERT INTO spectator_links "
                    "(id, session_id, token_sha256, label, created_at, expires_at, "
                    "link_nonce) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        link.id,
                        link.session_id,
                        hash_token(token) if keys is None else keys.verifier,
                        link.label,
                        link.created_at,
                        link.expires_at,
                        nonce,
                    ),
                )
                await self._conn.commit()
            except sqlite3.Error:
                await self._conn.rollback()
                await self._forget_tokens([link.id])
                raise
            await self._forget_tokens(replaced)
            if keys is None:
                await self._keep_token(link, token)
        if replaced:
            logger.info(
                "spectator_link_replaced",
                session_id=session_id,
                link_id=link.id,
                replaced=list(replaced),
            )
        logger.info(
            "spectator_link_minted",
            link_id=link.id,
            session_id=session_id,
            expires_at=link.expires_at,
        )
        return MintedLink(link=link, token=token, replaced=replaced)

    async def _keep_token(self, link: SpectatorLink, token: str,
                          content_key: Optional[bytes] = None) -> bool:
        if self._tokens is None:
            return False
        try:
            await self._tokens.execute(
                "INSERT OR REPLACE INTO spectator_link_tokens "
                "(link_id, token, expires_at, content_key) VALUES (?, ?, ?, ?)",
                (link.id, token, link.expires_at, content_key),
            )
            await self._tokens.commit()
        except sqlite3.Error as exc:
            logger.error(
                "spectator_link_token_not_kept", link_id=link.id, err=str(exc)
            )
            return False
        return True

    async def live_token(self, link_id: str) -> Optional[str]:
        assert self._conn is not None, "SpectatorLinksStore.init() not called"
        if self._tokens is None:
            return None
        now = int(time.time())
        async with self._lock:
            await self._sweep_expired_tokens(now)
            cur = await self._conn.execute(
                "SELECT 1 FROM spectator_links "
                "WHERE id = ? AND revoked_at IS NULL AND expires_at > ?",
                (link_id, now),
            )
            live = await cur.fetchone()
            await cur.close()
            if live is None:
                return None
            try:
                cur = await self._tokens.execute(
                    "SELECT token FROM spectator_link_tokens "
                    "WHERE link_id = ? AND expires_at > ?",
                    (link_id, now),
                )
                row = await cur.fetchone()
                await cur.close()
            except sqlite3.Error as exc:
                logger.error(
                    "spectator_link_token_unreadable", link_id=link_id, err=str(exc)
                )
                return None
        return None if row is None else str(row[0])

    async def get(self, link_id: str) -> Optional[SpectatorLink]:
        assert self._conn is not None, "SpectatorLinksStore.init() not called"
        async with self._lock:
            cur = await self._conn.execute(
                f"SELECT {_COLUMNS} FROM spectator_links WHERE id = ?",
                (link_id,),
            )
            row = await cur.fetchone()
            await cur.close()
        return None if row is None else _row_to_link(row)

    async def list_for_session(
        self, session_id: str, include_dead: bool = False
    ) -> List[SpectatorLink]:
        assert self._conn is not None, "SpectatorLinksStore.init() not called"
        async with self._lock:
            cur = await self._conn.execute(
                f"SELECT {_COLUMNS} FROM spectator_links "
                "WHERE session_id = ? ORDER BY created_at DESC, id DESC",
                (session_id,),
            )
            rows = await cur.fetchall()
            await cur.close()
        links = [_row_to_link(row) for row in rows]
        if include_dead:
            return links
        now = int(time.time())
        return [link for link in links if link.is_live(now)]

    async def list_live(self) -> List[SpectatorLink]:
        assert self._conn is not None, "SpectatorLinksStore.init() not called"
        async with self._lock:
            cur = await self._conn.execute(
                f"SELECT {_COLUMNS} FROM spectator_links ORDER BY created_at DESC, id DESC")
            rows = await cur.fetchall()
            await cur.close()
        now = int(time.time())
        return [link for link in (_row_to_link(row) for row in rows) if link.is_live(now)]

    async def live_expiry_by_session(self) -> Dict[str, int]:
        assert self._conn is not None, "SpectatorLinksStore.init() not called"
        now = int(time.time())
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT session_id, expires_at FROM spectator_links "
                "WHERE revoked_at IS NULL AND expires_at > ?",
                (now,),
            )
            rows = await cur.fetchall()
            await cur.close()
        expiry: Dict[str, int] = {}
        for row in rows:
            session_id = str(row[0])
            expires_at = int(row[1])
            if expires_at > expiry.get(session_id, 0):
                expiry[session_id] = expires_at
        return expiry

    async def live_relay_declarations(
        self,
    ) -> List[Tuple[str, str, str, Optional[str], int, Optional[bytes]]]:
        assert self._conn is not None, "SpectatorLinksStore.init() not called"
        now = int(time.time())
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT id, session_id, token_sha256, link_nonce, expires_at "
                "FROM spectator_links "
                "WHERE revoked_at IS NULL AND expires_at > ? ORDER BY id",
                (now,),
            )
            rows = await cur.fetchall()
            await cur.close()
            await self._sweep_expired_tokens(now)
            keys = await self._content_keys()
        return [(str(r[0]), str(r[1]), str(r[2]), None if r[3] is None else str(r[3]),
                 int(r[4]), keys.get(str(r[0])))
                for r in rows]

    async def _content_keys(self) -> Dict[str, bytes]:
        if self._tokens is None:
            return {}
        try:
            cur = await self._tokens.execute(
                "SELECT link_id, content_key FROM spectator_link_tokens "
                "WHERE content_key IS NOT NULL")
            rows = await cur.fetchall()
            await cur.close()
        except sqlite3.Error as exc:
            logger.error("spectator_link_keys_unreadable", err=str(exc))
            return {}
        return {str(r[0]): bytes(r[1]) for r in rows if len(r[1] or b"") == 32}

    async def revoke(self, link_id: str) -> Optional[SpectatorLink]:
        assert self._conn is not None, "SpectatorLinksStore.init() not called"
        now = int(time.time())
        async with self._lock:
            await self._conn.execute(
                "UPDATE spectator_links SET revoked_at = ? "
                "WHERE id = ? AND revoked_at IS NULL",
                (now, link_id),
            )
            await self._conn.commit()
            await self._forget_tokens((link_id,))
            cur = await self._conn.execute(
                f"SELECT {_COLUMNS} FROM spectator_links WHERE id = ?",
                (link_id,),
            )
            row = await cur.fetchone()
            await cur.close()
        if row is None:
            return None
        logger.info("spectator_link_revoked", link_id=link_id)
        return _row_to_link(row)

    async def purge_expired(self) -> int:
        assert self._conn is not None, "SpectatorLinksStore.init() not called"
        cutoff = int(time.time()) - PURGE_GRACE_SECONDS
        async with self._lock:
            cur = await self._conn.execute(
                "DELETE FROM spectator_links WHERE expires_at < ?",
                (cutoff,),
            )
            deleted = cur.rowcount or 0
            await cur.close()
            await self._conn.commit()
            await self._sweep_expired_tokens(int(time.time()))
        if deleted:
            logger.info("spectator_links_purge", deleted=deleted, cutoff=cutoff)
        return deleted

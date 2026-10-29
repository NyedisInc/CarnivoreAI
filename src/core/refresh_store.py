
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import List, Optional

import aiosqlite
import structlog

from src.core.refresh_rotation.replay import RotationReplayCache

logger = structlog.get_logger()


_PURGE_GRACE_SECONDS = 86400


class RefreshStoreNotReady(RuntimeError):
    pass


def _short(jti: str) -> str:
    return jti[:8] + "…"


class RefreshStore:

    def __init__(self, db_path: str, *, recent_rotations: Optional[RotationReplayCache] = None):
        self._db_path = str(Path(db_path).expanduser())
        self.recent_rotations = recent_rotations if recent_rotations is not None else RotationReplayCache()
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                jti TEXT PRIMARY KEY,
                user TEXT NOT NULL,
                exp INTEGER NOT NULL,
                revoked INTEGER DEFAULT 0,
                superseded_by TEXT,
                superseded_at INTEGER
            )
            """
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_exp "
            "ON refresh_tokens(exp)"
        )
        await self._conn.commit()
        try:
            Path(self._db_path).chmod(0o600)
        except OSError as e:
            logger.warning("refresh_store_chmod_failed", db=self._db_path, err=str(e))
        logger.info("refresh_store_initialized", db=self._db_path)

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RefreshStoreNotReady("RefreshStore.init() not called")
        return self._conn

    async def issue(self, jti: str, user: str, exp: int) -> None:
        self._require_conn()
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO refresh_tokens (jti, user, exp) VALUES (?, ?, ?)",
                (jti, user, int(exp)),
            )
            await self._conn.commit()

    async def rotate(
        self,
        old_jti: str,
        new_jti: str,
        user: str,
        new_exp: int,
    ) -> bool:
        conn = self._require_conn()
        now = int(time.time())
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT revoked, superseded_by, superseded_at, exp "
                "FROM refresh_tokens WHERE jti = ?",
                (old_jti,),
            )
            row = await cur.fetchone()
            await cur.close()

            if row is None:
                logger.warning("refresh_rotate_unknown_jti", jti=_short(old_jti))
                return False

            revoked, superseded_by, _superseded_at, old_exp = row

            if revoked:
                logger.warning("refresh_rotate_revoked", jti=_short(old_jti))
                return False
            if superseded_by is not None:
                logger.warning(
                    "refresh_rotate_already_superseded",
                    jti=_short(old_jti),
                    superseded_by=_short(superseded_by),
                )
                return False
            if old_exp <= now:
                logger.warning("refresh_rotate_expired", jti=_short(old_jti))
                return False

            try:
                await conn.execute(
                    "UPDATE refresh_tokens "
                    "SET superseded_by = ?, superseded_at = ? "
                    "WHERE jti = ?",
                    (new_jti, now, old_jti),
                )
                await conn.execute(
                    "INSERT INTO refresh_tokens (jti, user, exp) VALUES (?, ?, ?)",
                    (new_jti, user, int(new_exp)),
                )
                await conn.commit()
            except sqlite3.Error:
                await conn.rollback()
                raise
            logger.info(
                "refresh_rotated",
                old_jti=old_jti[:8] + "…",
                new_jti=new_jti[:8] + "…",
            )
            return True

    async def revoke(self, jti: str) -> None:
        self._require_conn()
        async with self._lock:
            await self._conn.execute(
                "UPDATE refresh_tokens SET revoked = 1 WHERE jti = ?",
                (jti,),
            )
            await self._conn.commit()
            logger.info("refresh_revoked", jti=jti[:8] + "…")

    async def revoke_chain(self, start_jti: str) -> int:
        self._require_conn()
        count = 0
        async with self._lock:
            current: Optional[str] = start_jti
            visited: set[str] = set()
            while current is not None and current not in visited:
                visited.add(current)
                await self._conn.execute(
                    "UPDATE refresh_tokens SET revoked = 1 WHERE jti = ?",
                    (current,),
                )
                count += 1
                cur = await self._conn.execute(
                    "SELECT superseded_by FROM refresh_tokens WHERE jti = ?",
                    (current,),
                )
                row = await cur.fetchone()
                await cur.close()
                current = row[0] if row and row[0] else None
            await self._conn.commit()
        logger.warning("refresh_chain_revoked", start=start_jti[:8] + "…", count=count)
        return count

    async def revoke_all(self) -> int:
        self._require_conn()
        async with self._lock:
            cur = await self._conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE revoked = 0")
            count = cur.rowcount
            await cur.close()
            await self._conn.commit()
        logger.warning("refresh_all_revoked", count=count)
        return count

    async def is_valid(self, jti: str, grace_seconds: int = 10) -> bool:
        self._require_conn()
        now = int(time.time())
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT revoked, superseded_at, exp FROM refresh_tokens "
                "WHERE jti = ?",
                (jti,),
            )
            row = await cur.fetchone()
            await cur.close()

        if row is None:
            return False
        revoked, superseded_at, exp = row
        if revoked:
            return False
        if exp <= now:
            return False
        if superseded_at is not None and (now - superseded_at) >= grace_seconds:
            return False
        return True

    async def is_superseded(self, jti: str) -> bool:
        self._require_conn()
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT superseded_at FROM refresh_tokens WHERE jti = ?",
                (jti,),
            )
            row = await cur.fetchone()
            await cur.close()
        return row is not None and row[0] is not None

    async def purge_expired(self) -> int:
        self._require_conn()
        cutoff = int(time.time()) - _PURGE_GRACE_SECONDS
        async with self._lock:
            cur = await self._conn.execute(
                "DELETE FROM refresh_tokens WHERE exp < ?",
                (cutoff,),
            )
            deleted = cur.rowcount or 0
            await cur.close()
            await self._conn.commit()
        if deleted:
            logger.info("refresh_purge", deleted=deleted, cutoff=cutoff)
        return deleted

    async def _all_jtis(self) -> List[str]:
        self._require_conn()
        async with self._lock:
            cur = await self._conn.execute("SELECT jti FROM refresh_tokens")
            rows = await cur.fetchall()
            await cur.close()
        return [r[0] for r in rows]


from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator, List, Optional

import structlog

from src.core.safe_io.readonly_db import connect_readonly
from src.core.db import table_exists
from src.core.inventory.claims import GENERIC, Claim, ClaimBook
from src.core.inventory.model import KIND_ROWS, REPORT, ROLE_KEY, ROLE_PATH, ROLE_SECRET, Artifact, FieldRef
from src.core.inventory.scope import Scope

logger = structlog.get_logger()

SIDE_DB_TIMEOUT_S = 10.0


def rewrite_fields(claim: Claim) -> List[FieldRef]:
    return ([FieldRef(c, ROLE_KEY) for c in claim.keys] + [FieldRef(c, ROLE_PATH) for c in claim.paths]
            + [FieldRef(c, ROLE_SECRET) for c in claim.secret])


@contextmanager
def open_side(path: Path) -> Iterator[Optional[sqlite3.Connection]]:
    if not Path(path).exists():
        yield None
        return
    with closing(connect_readonly(path, timeout=SIDE_DB_TIMEOUT_S)) as conn:
        conn.row_factory = sqlite3.Row
        yield conn


def _artifact(claim: Claim, scope: Scope, book: ClaimBook, conn: sqlite3.Connection, db_path: Optional[Path]) -> Optional[Artifact]:
    if claim.where is None or not table_exists(conn, claim.table):
        return None
    where = claim.where(scope, book)
    if where is None:
        return None
    sql, params = where
    locator = {"table": claim.table, "where": sql, "params": list(params), "db": str(db_path) if db_path else None}
    try:
        count = int(conn.execute(f"SELECT COUNT(*) FROM {claim.table} WHERE {sql}", params).fetchone()[0])
    except sqlite3.Error as exc:
        logger.warning("inventory_claim_unreadable", store=claim.store, table=claim.table, error=str(exc))
        return Artifact(store=claim.store, kind=KIND_ROWS, what=claim.table, count=0, action=REPORT,
                        reason=f"could not be read ({type(exc).__name__}: {exc}); nothing there is counted",
                        locator=locator, rewrite=rewrite_fields(claim), derived=claim.derived)
    if not count:
        return None
    return Artifact(store=claim.store, kind=KIND_ROWS, what=claim.table, count=count, action=claim.purge,
                    reason=claim.note if claim.purge == REPORT else "", locator=locator, rewrite=rewrite_fields(claim),
                    derived=claim.derived)


def trace_claims(book: ClaimBook, scope: Scope, store: str, conn: sqlite3.Connection,
                 db_path: Optional[Path] = None) -> List[Artifact]:
    out: List[Artifact] = []
    for claim in book.claims:
        if claim.store != store or claim.handler != GENERIC or scope.kind not in claim.scopes:
            continue
        art = _artifact(claim, scope, book, conn, db_path)
        if art is not None:
            out.append(art)
    return out


def annotate(book: ClaimBook, arts: List[Artifact], scope: Scope) -> None:
    for art in arts:
        if art.kind != KIND_ROWS or art.rewrite:
            continue
        claim = next((c for c in book.claims_for(art.store, art.table) if scope.kind in c.scopes), None)
        if claim is not None:
            art.rewrite = rewrite_fields(claim)
            art.derived = claim.derived


from __future__ import annotations

import sqlite3
from typing import Callable, Iterable, Mapping, Optional, Sequence, Tuple, TypeVar

from src.cplugs.publicboard import links, minting
from src.cplugs.publicboard.deps import BoardMissing, CheckResult, LinkRow, ReadDeps, RevisionRead, Unavailable, Unscannable
from src.cplugs.publicboard.read import TICKET_LABEL, TICKET_TTL_S
from src.cplugs.sdk import CplugContext, CplugSchemaError
from src.cplugs.sdk.board_public import PublicBoardMissing, PublicBoardUnavailable, port
from src.cplugs.sdk.file_secrets import ScanTimeout
from src.cplugs.sdk.signed_links import SigningUnavailable, mint, verify

T = TypeVar("T")


def _guarded(call: Callable[[], T]) -> T:
    try:
        return call()
    except (CplugSchemaError, sqlite3.Error, OSError) as exc:
        raise Unavailable(type(exc).__name__) from exc


def build(ctx: CplugContext) -> ReadDeps:
    storage = ctx.storage

    def check(token: str) -> CheckResult:
        return _guarded(lambda: links.check(storage, token))

    def active(link_id: str) -> Optional[LinkRow]:
        return _guarded(lambda: links.active(storage, link_id))

    def advance(link_id: str, revision: str, fingerprint: str) -> int:
        return _guarded(lambda: links.advance(storage, link_id, revision, fingerprint))

    def revision(board: str, rev: str, view: Optional[str]) -> Optional[RevisionRead]:
        boards = port()
        if boards is None:
            return None
        try:
            return boards.public_revision(board, rev, view)
        except PublicBoardMissing as exc:
            raise BoardMissing(str(exc)) from exc
        except (PublicBoardUnavailable, OSError) as exc:
            raise Unavailable(type(exc).__name__) from exc

    def scan(texts: Sequence[str]) -> Mapping[str, int]:
        try:
            return minting.scan_texts(texts)
        except ScanTimeout as exc:
            raise Unscannable("timeout") from exc

    def mint_ticket(fields: Sequence[str]) -> str:
        try:
            return mint(TICKET_LABEL, fields, TICKET_TTL_S)
        except SigningUnavailable as exc:
            raise Unavailable("signing") from exc

    def open_ticket(ticket: str) -> Optional[Tuple[str, ...]]:
        try:
            return verify(TICKET_LABEL, ticket, 3)
        except SigningUnavailable as exc:
            raise Unavailable("signing") from exc

    def matches(link: LinkRow, texts: Iterable[str]) -> bool:
        return links.content_matches(link, texts)  # type: ignore[arg-type]

    return ReadDeps(check=check, active=active, advance=advance, revision=revision, matches=matches, fingerprint=links.content_hash,
                    scan=scan, mint_ticket=mint_ticket, open_ticket=open_ticket)

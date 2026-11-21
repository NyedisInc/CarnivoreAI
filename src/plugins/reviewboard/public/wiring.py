
from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple, TypeVar

import structlog

from src.plugins.reviewboard.public import announce, drafts, links, minting, presence, responses
from src.plugins.reviewboard.public.deps import (BoardMissing, CapSpent, CheckResult, LinkRow, ReadDeps, RevisionRead, StoredPost, Unavailable, Unscannable,
                                         WriteDeps)
from src.plugins.reviewboard.public.read import TICKET_LABEL, TICKET_TTL_S
from src.plugins.sdk import CplugContext, CplugSchemaError
from src.plugins.reviewboard.public.port import PublicBoardMissing, PublicBoardUnavailable, port
from src.plugins.sdk.file_secrets import ScanTimeout
from src.plugins.sdk.signed_links import SigningUnavailable, mint, verify

T = TypeVar("T")
logger = structlog.get_logger()
TIMER: Dict[str, Optional[asyncio.TimerHandle]] = {"at": None}
PRUNE_EVERY_S = 3600.0


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

    def own_draft(link_id: str, key: str, rev: str) -> Optional[Mapping[str, object]]:
        store = responses.storage_for(storage.path)

        def read() -> Optional[Mapping[str, object]]:
            visitor = drafts.find_visitor(store, link_id, key)
            return None if visitor is None else drafts.own_draft(store, visitor.id, rev)
        return _guarded(read)

    def follow(listener: Callable[[], None]) -> Callable[[], None]:
        boards = port()
        return boards.follow(listener) if boards is not None else (lambda: None)

    def latest(board: str) -> Optional[str]:
        boards = port()
        if boards is None:
            return None
        try:
            return boards.latest(board)
        except (PublicBoardMissing, PublicBoardUnavailable, OSError):
            return None

    def served(link_id: str, rev: str) -> bool:
        return _guarded(lambda: links.served(storage, link_id, rev))

    def served_revisions(link_id: str) -> Sequence[str]:
        return _guarded(lambda: links.served_revisions(storage, link_id))

    def answered_revisions(link_id: str, key: str) -> Sequence[str]:
        store = responses.storage_for(storage.path)

        def read() -> Sequence[str]:
            visitor = drafts.find_visitor(store, link_id, key)
            return [] if visitor is None else drafts.answered_revisions(store, visitor.id)
        return _guarded(read)

    def board_theme(board: str) -> Optional[Mapping[str, str]]:
        boards = port()
        if boards is None:
            return None
        try:
            return boards.board_theme(board)
        except (PublicBoardMissing, PublicBoardUnavailable, OSError) as exc:
            logger.info("publicboard_board_theme_unread", board=board, error_type=type(exc).__name__)
            return None

    def beat(link_id: str, board: str, key: str) -> None:
        if presence.PRESENCE.touch(board, (link_id, drafts.key_hash(key)), time.monotonic()):
            announce.changed(ctx, board)
        handle = TIMER["at"]
        if handle is None or handle.cancelled():
            TIMER["at"] = asyncio.get_running_loop().call_later(_until_next(), rearm)

    def _until_next() -> float:
        wait = presence.PRESENCE.next_expiry(time.monotonic())
        return (presence.TTL_S if wait is None else wait) + 0.5

    def rearm() -> None:
        TIMER["at"] = None
        sweep_presence(ctx, time.monotonic())
        if presence.PRESENCE.any():
            TIMER["at"] = asyncio.get_running_loop().call_later(_until_next(), rearm)

    return ReadDeps(check=check, active=active, advance=advance, revision=revision, matches=matches, fingerprint=links.content_hash,
                    scan=scan, mint_ticket=mint_ticket, open_ticket=open_ticket, ticket_ttl_s=TICKET_TTL_S, own_draft=own_draft, follow=follow,
                    latest=latest, served=served, board_theme=board_theme, served_revisions=served_revisions, answered_revisions=answered_revisions, beat=beat)


def cancel_presence_timer() -> None:
    handle = TIMER["at"]
    if handle is not None:
        handle.cancel()
    TIMER["at"] = None


def sweep_presence(ctx: CplugContext, now: float) -> None:
    for board in presence.PRESENCE.expire(now):
        announce.changed(ctx, board)


def build_write(ctx: CplugContext) -> WriteDeps:
    storage = ctx.storage
    due = {"at": time.monotonic() + PRUNE_EVERY_S}

    def prune() -> int:
        due["at"] = time.monotonic() + PRUNE_EVERY_S
        return _guarded(lambda: drafts.prune(responses.storage_for(storage.path)))

    def prune_if_due() -> None:
        if time.monotonic() < due["at"]:
            return
        try:
            prune()
        except Unavailable as exc:
            logger.warning("publicboard_prune_failed", where="write", error=str(exc))

    def check(board: str, revision: str, kind: str, body: Mapping[str, object]) -> Optional[Sequence[str]]:
        boards = port()
        if boards is None:
            return None
        try:
            return boards.check_post(board, revision, kind, body)
        except PublicBoardMissing as exc:
            raise BoardMissing(str(exc)) from exc
        except OSError as exc:
            raise Unavailable(type(exc).__name__) from exc

    def visitor(link_id: str, board: str, key: str) -> drafts.Visitor:
        try:
            return _guarded(lambda: drafts.visitor_for(responses.storage_for(storage.path), link_id, board, key))
        except drafts.VisitorsFull as exc:
            raise CapSpent("visitors") from exc

    def add(link_id: str, board: str, revision: str, kind: str, name: Optional[str], body: Mapping[str, object], client_post_id: str,
            key: Optional[str]) -> StoredPost:
        store = responses.storage_for(storage.path)
        try:
            stored = _guarded(lambda: responses.add(store, link_id=link_id, board=board, revision=revision, kind=kind,  # type: ignore[arg-type]
                                                    name=name, body=body, client_post_id=client_post_id, visitor_key=key))
        except responses.CapReached as exc:
            raise CapSpent(exc.which) from exc
        if not stored.duplicate:
            announce.posted(ctx, store, board=board, body=body)
        prune_if_due()
        return stored

    def save_draft(link_id: str, board: str, key: str, revision: str, body: Mapping[str, object]) -> bool:
        store = responses.storage_for(storage.path)
        sender = visitor(link_id, board, key)
        changed = _guarded(lambda: drafts.save_draft(store, sender.id, revision, body))
        if changed:
            announce.changed(ctx, board)
        prune_if_due()
        return changed

    return WriteDeps(check=check, store=add, save_draft=save_draft, prune=prune)

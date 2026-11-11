
from __future__ import annotations

from typing import Any, List, Mapping

import structlog

from src.cplugs.reviewboard.public import responses
from src.cplugs.sdk.owner_text import stored_text
from src.cplugs.sdk.visible_text import keep_visible, normalize
from src.cplugs.reviewboard.public.port import PublicBoardMissing, PublicBoardUnavailable, port
from src.cplugs.sdk.context import CapabilityMissing
from src.cplugs.sdk.storage import CplugStorage

logger = structlog.get_logger()

TOPIC = "visitors"
ALERT_TITLE_KEY = "cplug.reviewboard.public.alert.visitor_posted"
ALERT_DETAIL_KEY = "cplug.reviewboard.public.alert.visitor_preview"
PREVIEW_MAX = 60
CUT = "..."
TITLE_MAX = 80
NOTIFY = "notify"


def alert_key(board: str) -> str:
    return f"visitors.{board}"


def _one_line(text: str) -> str:
    return " ".join(word for word in (keep_visible(w) for w in normalize(text).split()) if word)


def _capped(line: str, limit: int, marker: str) -> str:
    if len(line) <= limit:
        return line
    return keep_visible(line[:limit - len(marker)].rstrip() + marker)


def label(title: str) -> str:
    return _capped(" ".join(stored_text(title).split()), TITLE_MAX, "")


def _typed(body: Mapping[str, Any]) -> List[str]:
    if isinstance(body.get("text"), str):
        return [body["text"]]
    payload = body.get("payload")
    if isinstance(payload, Mapping):
        notes = payload.get("notes")
        return [v for v in notes.values() if isinstance(v, str)] if isinstance(notes, Mapping) else []
    out: List[str] = []
    for answer in body.get("answers") or []:
        if isinstance(answer, Mapping):
            out += [answer[k] for k in ("text", "note") if isinstance(answer.get(k), str)]
    return out


def preview(body: Mapping[str, Any]) -> str:
    for text in _typed(body):
        line = _one_line(text)
        if line:
            return _capped(line, PREVIEW_MAX, CUT)
    return ""


def board_title(board: str) -> str:
    boards = port()
    if boards is None:
        return board
    try:
        return boards.revision_texts(board).title or board
    except (PublicBoardMissing, PublicBoardUnavailable, OSError) as exc:
        logger.info("publicboard_alert_title_fallback", board=board, error_type=type(exc).__name__)
        return board


def changed(ctx: Any, board: str) -> None:
    ctx.notify(TOPIC, board)


def _raise(ctx: Any, board: str, count: int, shown: str, *, only_if_open: bool = False) -> None:
    if not ctx.has(NOTIFY):
        logger.info("publicboard_visitor_alert_skipped", reason="notify_not_granted", board=board)
        return
    params = {"board": label(board_title(board)), "count": count, "preview": shown}
    try:
        ctx.alert(alert_key(board), "info", ALERT_TITLE_KEY, params, detail_key=ALERT_DETAIL_KEY if shown else None, only_if_open=only_if_open)
    except CapabilityMissing:
        logger.info("publicboard_visitor_alert_skipped", reason="capability_missing", board=board)


def _close(ctx: Any, board: str) -> None:
    try:
        ctx.alert_resolve(alert_key(board))
    except CapabilityMissing:
        logger.info("publicboard_visitor_alert_close_skipped", reason="capability_missing", board=board)


def posted(ctx: Any, store: CplugStorage, *, board: str, body: Mapping[str, Any]) -> None:
    changed(ctx, board)
    _raise(ctx, board, responses.waiting(store, board), preview(body))


def settled(ctx: Any, store: CplugStorage, board: str) -> None:
    changed(ctx, board)
    count = responses.waiting(store, board)
    if count == 0:
        _close(ctx, board)
    else:
        _raise(ctx, board, count, "", only_if_open=True)

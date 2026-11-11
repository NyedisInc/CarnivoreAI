
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Optional

import structlog

from src.core.notifications import card_contract as cc
from src.core.notifications.cards.build import build_card
from src.core.notifications.cards.model import Built, say
from src.core.notifications.styles import effective_style
from src.core.notify_caps.store import get_store

logger = structlog.get_logger()


@dataclass
class Prepared:

    payload: Dict[str, Any]
    built: Built
    cap: Optional[str]


async def _mint(built: Built, device_row_id: str) -> Optional[tuple]:
    target = built.target or {"type": "media" if built.media else "none"}
    media_ids = [built.media["id"]] if built.media and built.media.get("id") else []
    try:
        return await asyncio.to_thread(
            get_store().mint, device_row_id=device_row_id, type_id=built.type_id, kind=built.kind, target=target,
            actions=dict(built.acts), media_ids=media_ids, card=built.full, ask=built.ask)
    except (ValueError, OSError, sqlite3.Error) as exc:
        logger.warning("notify_cap_mint_failed", kind=built.kind, error_type=type(exc).__name__)
        return None


async def prepare(event: Any, dest_id: str, device_row_id: str) -> Prepared:
    built = await build_card(event, dest_id)
    cap, ttl, acts = None, None, built.acts
    if built.needs_cap:
        minted = await _mint(built, device_row_id)
        if minted is None:
            acts = [("open", say("notify.card.act.open"))]
        else:
            cap, ttl = minted[0], int(minted[1])
    style = effective_style(event.type_id)
    payload = cc.build_payload(
        kind=built.kind, type_id=built.type_id, title=built.title, body=built.body, path=built.path, thread=built.thread,
        sub=built.sub, lv=style.level, snd=style.sound, cap=cap, ttl=ttl, acts=acts, card=built.card,
        more=cap is not None and built.full != built.card, media=built.media)
    return Prepared(payload, built, cap)


from __future__ import annotations

from typing import Any, Dict, Optional

from src.core.notifications import card_contract as cc
from src.core.notifications.cards import builders, sources
from src.core.notifications.cards.model import Built, Ctx, clip, clock, fit_card, say
from src.core.notifications.kinds import webpush

ASK_TYPES = frozenset({"session.question", "session.permission", "session.plan_approval", "approval.folder_trust"})
_TITLES = {"yesno": "ask", "choice": "ask"}
_SUBS = {"died": "died", "appupdate": "appupdate", "swarm": "swarm", "crosstalk": "crosstalk", "signin": "signin"}


def choose_kind(event: Any, dialog: Optional[Dict[str, Any]], hint: Dict[str, Any]) -> str:
    media = hint.get("media")
    if media:
        mime = str(media.get("mime") or "")
        return str(media.get("kind") or ("image" if mime.startswith("image/") else "video" if mime.startswith("video/") else "file"))
    if hint.get("url"):
        return "link"
    if event.type_id == "session.question":
        return "choice" if dialog and not (dialog.get("plain_yes") or dialog.get("plain_no")) else "yesno"
    return cc.kind_for_type(event.type_id)


def _title(kind: str, ctx: Ctx, fixed: str) -> str:
    if kind == "notice":
        return fixed
    return say(f"notify.card.title.{_TITLES.get(kind, kind)}", agent=ctx.agent, account=ctx.hint.get("account", ""))


def _sub(kind: str, ctx: Ctx) -> str:
    word = say(f"notify.card.word.{kind}")
    if kind in _SUBS:
        return say(f"notify.card.sub.{_SUBS[kind]}", agent=ctx.agent, computer=ctx.computer, provider=ctx.hint.get("provider", "claude"))
    return say("notify.card.sub.default", word=word, computer=ctx.computer)


def _body(card: Dict[str, Any], fixed: str) -> str:
    text = card.get("ask") or card.get("text") or card.get("body")
    if not text and card.get("cmd"):
        text = "\n".join(card["cmd"][:3])
    if not text and card.get("caption"):
        text = card["caption"]
    if card.get("host") and card.get("url"):
        text = f"{text or fixed} · {card['host']}"
    return clip(text or fixed, cc.LIMITS["body"])


async def build_card(event: Any, dest_id: str = "", *, detail: Optional[bool] = None) -> Built:
    src = sources.current()
    dialog = await src.dialog(event.session_id) if event.type_id in ASK_TYPES and event.session_id else None
    hint = {**await src.extra(event), **(event.card_hint or {})}
    on = src.details_on(dest_id) if detail is None else detail
    kind = choose_kind(event, dialog, hint)
    ctx = Ctx(event, dialog, hint, str(hint.get("agent") or event.session_ref or "carnivore"), event.computer or "", on, kind)
    part = builders.BUILDERS[kind](ctx)
    fixed = webpush.build_payload(event)
    base = {"strip": [say(f"notify.card.word.{kind}"), "" if kind in cc.STRIP_WITHOUT_AGENT else ctx.agent, ctx.computer], "agent": ctx.agent, "computer": ctx.computer,
            "ts": clock(event.ts)}
    card = fit_card({**base, **part.card})
    full = {**base, **part.card, **part.full}
    thread = f"{event.origin}|{event.session_id}" if event.session_id else str(fixed.get("thread", ""))
    return Built(kind=kind, type_id=event.type_id, title=_title(kind, ctx, fixed["title"]), body=_body(part.card, fixed["body"]),
                 sub=_sub(kind, ctx), path=fixed["path"], thread=thread, card=card, full=full, acts=part.acts,
                 target=part.target, ask=part.ask, media=part.media, session_id=event.session_id or "",
                 fingerprint=str((dialog or {}).get("fingerprint") or ""),
                 item=str(hint.get("item")) if kind == "swarm" and str(hint.get("item") or "").isdigit() else "")

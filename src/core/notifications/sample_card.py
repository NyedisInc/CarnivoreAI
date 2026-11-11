
from __future__ import annotations

import time
from typing import Any, Dict

from src.core.notifications import card_contract, styles

SAMPLE_TITLE = "sample notification"
SAMPLE_BODY = "this is a test of how this type looks and sounds"


def sample_hint(type_id: str, computer: str = "") -> Dict[str, Any]:
    kind = card_contract.kind_for_type(type_id)
    style = styles.effective_style(type_id)
    card: Dict[str, Any] = {"strip": [kind, "sample", computer], "agent": "sample", "computer": computer,
                            "ts": time.strftime("%H:%M")}
    if kind == "notice":
        card.update(title=SAMPLE_TITLE, body=SAMPLE_BODY)
    payload = card_contract.build_payload(
        kind=kind, type_id=type_id, title=SAMPLE_TITLE, body=SAMPLE_BODY, path="/", thread="sample|sample",
        lv=style.level, snd=style.sound, card=card)
    return {"sample": True, "kind": kind, "snd": payload["snd"], "lv": payload["lv"], "card": payload.get("card", card),
            "title": payload["title"], "body": payload["body"]}

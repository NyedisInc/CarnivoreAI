
from __future__ import annotations

from typing import Any, Dict

from src.cplugs.sdk import ports
from src.cplugs.sdk.owner_reply import NAME, OwnerReplyDeclined, OwnerReplyRefused, OwnerReplyUnavailable

__all__ = ["NAME", "OwnerReplyDeclined", "OwnerReplyRefused", "OwnerReplyUnavailable", "owner_reply"]


async def owner_reply(app_state: Any, item_id: int, text: str) -> Dict[str, Any]:
    port = ports.get(NAME)
    if port is None:
        raise OwnerReplyUnavailable(NAME)
    return await port.owner_reply(app_state, item_id, text)

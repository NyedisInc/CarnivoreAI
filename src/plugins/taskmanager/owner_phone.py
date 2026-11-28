
from __future__ import annotations

from typing import Any, Dict

from src.plugins.taskmanager import reply
from src.plugins.taskmanager.rules import TaskManagerError
from src.plugins.sdk import CplugContext, ports
from src.plugins.sdk.owner_reply import NAME, OwnerReplyDeclined, OwnerReplyRefused


class OwnerReplyPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx

    async def owner_reply(self, app_state: Any, item_id: int, text: str) -> Dict[str, Any]:
        try:
            return await reply.post_reply(self._ctx, item_id, text)
        except reply.CardRefused as exc:
            raise OwnerReplyDeclined(str(exc)) from exc
        except TaskManagerError as exc:
            raise OwnerReplyRefused(str(getattr(exc, "code", "refused"))) from exc


def register(ctx: CplugContext) -> None:
    ports.register(NAME, OwnerReplyPort(ctx))


def unregister() -> None:
    ports.unregister(NAME)

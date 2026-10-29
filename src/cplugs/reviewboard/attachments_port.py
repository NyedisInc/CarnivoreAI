
from __future__ import annotations

from typing import Any, Dict

import structlog

from src.cplugs.reviewboard import attachments, service, wire
from src.cplugs.reviewboard.errors import BoardError, BoardNotFound, NoRoot
from src.cplugs.sdk import CplugContext, ports

logger = structlog.get_logger()

NAME = "reviewboard.attachments"


class AttachmentsPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx

    def lists_file(self, item_id: int, file_id: str) -> bool:
        try:
            root = wire.board_root(self._ctx)
        except NoRoot as exc:
            logger.debug("reviewboard_attachments_port_no_root", reason=getattr(exc, "reason", ""))
            return False
        for row in service.boards(root)["boards"]:
            try:
                sidecar: Dict[str, Any] = service.board(root, row["slug"]).get("sidecar") or {}
            except BoardNotFound:
                continue
            except BoardError as exc:
                raise OSError(f"a board could not be read: {exc.code}") from exc
            if any(e["item_id"] == item_id and e["file_id"] == file_id and not attachments.is_removed(e) for e in attachments.entries_of(sidecar)):
                return True
        return False


def register(ctx: CplugContext) -> None:
    ports.register(NAME, AttachmentsPort(ctx))


def unregister() -> None:
    ports.unregister(NAME)


from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Sequence, Tuple

from src.cplugs.reviewboard.errors import NoTaskManager
from src.cplugs.sdk import ports
from src.cplugs.sdk.file_deletion import FileDeletion

NAME = "huddle.board"


class BoardPort(Protocol):

    async def item_info(self, item_id: int) -> Optional[Dict[str, Any]]:
        pass

    async def items_info(self, item_ids: Sequence[int]) -> Optional[Dict[int, Dict[str, Any]]]:
        pass

    async def check_caller(self, caller: Any, item_id: int, cross_project: bool) -> None:
        pass

    async def add_task(self, caller: Any, *, title: str, text: str) -> Dict[str, Any]:
        pass

    async def post_card(self, caller: Any, item_id: int, *, text: str, card: Dict[str, Any], request_review: bool,
                        review: Dict[str, str], cross_project: bool) -> Dict[str, Any]:
        pass

    async def post_reply(self, item_id: int, text: str, ref: Dict[str, str]) -> Dict[str, Any]:
        pass

    async def tell_session(self, session_id: str, text: str) -> Dict[str, Any]:
        pass

    async def attach_files(self, caller: Any, item_id: int, *, uploads: Sequence[Tuple[str, bytes]], text: str, request_review: bool,
                           review: Dict[str, str], cross_project: bool) -> Dict[str, Any]:
        pass

    async def caller_key(self, caller: Any) -> Optional[str]:
        pass

    async def delete_file(self, item_id: int, message_id: int, file_id: str, *, name: str, size: int, sha256: str) -> FileDeletion:
        pass

    def file_url(self, item_id: int, file_id: str) -> str:
        pass


def find() -> Optional[BoardPort]:
    return ports.get(NAME)


def get() -> BoardPort:
    port = find()
    if port is None:
        raise NoTaskManager("the task manager is off, so a board cannot reach its task")
    return port


from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Sequence, Tuple

from src.cplugs.reviewboard.errors import NoTaskManager
from src.cplugs.sdk import ports

NAME = "huddle.board"


class BoardPort(Protocol):

    async def item_info(self, item_id: int) -> Optional[Dict[str, Any]]:
        pass

    async def items_info(self, item_ids: Sequence[int]) -> Optional[Dict[int, Dict[str, Any]]]:
        """Many tasks in ONE call (the board list, #1793): {item id: the same dict :meth:`item_info` answers} for each live item; an id with
        no live item is left out. None when the Task Manager's store could not be read at all (the list then shows no board as closed)."""

    async def check_caller(self, caller: Any, item_id: int, cross_project: bool) -> None:
        pass

    async def add_task(self, caller: Any, *, title: str, text: str) -> Dict[str, Any]:
        """File a new task for a board that has none yet (a scratch board): on the calling pane's own project list, else the shared list,
        parked in ``todo``. Output: {filed: True, task: <item_info>} or {filed: False, reason}; it does not raise for a refusal."""

    async def post_card(self, caller: Any, item_id: int, *, text: str, card: Dict[str, Any], request_review: bool,
                        review: Dict[str, str], cross_project: bool) -> Dict[str, Any]:
        pass

    async def post_reply(self, item_id: int, text: str, ref: Dict[str, str]) -> Dict[str, Any]:
        pass

    async def tell_session(self, session_id: str, text: str) -> Dict[str, Any]:
        pass

    async def attach_files(self, caller: Any, item_id: int, *, uploads: Sequence[Tuple[str, bytes]], text: str, request_review: bool,
                           review: Dict[str, str], cross_project: bool) -> Dict[str, Any]:
        """Store each (safe name, checked bytes) as the task's own file (the Task Manager's file store, its ``pastes/`` folder) and post ONE claude
        info on the item carrying them; when ``request_review``, move the item to review as :meth:`post_card` does (``attachments.py``).
        Output: {message_id, files: [{id, name, mime, size}], review: {requested, moved, reason}, ...the guard's fields}; ``message_id`` is
        None when nothing was attached (no file is left behind): the item is gone, or ``refused`` and ``code`` say why (the Task Manager's own
        refusal code, or ``store_failed`` when a file could not be written). Raises: ToolError (the guard)."""

    def file_url(self, item_id: int, file_id: str) -> str:
        pass


def find() -> Optional[BoardPort]:
    return ports.get(NAME)


def get() -> BoardPort:
    port = find()
    if port is None:
        raise NoTaskManager("the huddle is off, so a board cannot reach its task")
    return port

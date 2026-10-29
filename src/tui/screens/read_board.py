
from __future__ import annotations

from typing import Any, Optional

import structlog
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Label

from src.tui.api_client import AuthRequired, ServerUnavailable
from src.tui.listing_store import LIVENESS
from src.tui.strings import t

logger = structlog.get_logger(__name__)

POLL_SECONDS = 30.0


class Board(DataTable[Any]):

    def action_cursor_down(self) -> None:
        super().action_cursor_down()

    def action_cursor_up(self) -> None:
        super().action_cursor_up()

    def action_top(self) -> None:
        self.move_cursor(row=0)

    def action_bottom(self) -> None:
        self.move_cursor(row=max(self.row_count - 1, 0))


class ReadBoardPane(Vertical):

    path = ""
    topic = ""
    pane_id = ""

    def __init__(self) -> None:
        super().__init__(id=self.pane_id)
        self.data: Optional[dict[str, Any]] = None
        self._unsub: Any = None
        self._timer: Any = None

    def make_board(self) -> Board:
        raise NotImplementedError

    def compose(self) -> ComposeResult:
        yield Label("", classes="read-summary")
        yield self.make_board()
        yield Label("", classes="read-note")

    def on_mount(self) -> None:
        self.setup_columns(self.query_one(Board))
        events = self.app.events  # type: ignore[attr-defined]
        self._unsub = events.on_topics(self._topics_changed)
        self._timer = self.set_interval(POLL_SECONDS, self._tick)
        self.run_worker(self.reload(), exclusive=True, group="reload")

    def on_unmount(self) -> None:
        if self._unsub:
            self._unsub()
        if self._timer:
            self._timer.stop()

    def setup_columns(self, board: Board) -> None:
        raise NotImplementedError

    def paint(self, board: Board, data: dict[str, Any]) -> str:
        raise NotImplementedError

    def _topics_changed(self, topics: list[str]) -> None:
        if self.topic in topics or LIVENESS in topics:
            self.run_worker(self.reload(), exclusive=True, group="reload")

    def _tick(self) -> None:
        if not self.app.events.topic_pushed(self.topic):  # type: ignore[attr-defined]
            self.run_worker(self.reload(), exclusive=True, group="reload")

    async def reload(self) -> None:
        note = self.query_one(".read-note", Label)
        try:
            resp = await self.app.client.request("GET", self.path)  # type: ignore[attr-defined]
        except AuthRequired:
            self.app.show_login()  # type: ignore[attr-defined]
            return
        except ServerUnavailable as exc:
            logger.info("tui_read_unavailable", path=self.path, error=type(exc).__name__)
            note.update(t("tui.read.unavailable"))
            return
        if resp.status_code != 200:
            note.update(t("tui.read.refused"))
            return
        self.data = resp.json()
        board = self.query_one(Board)
        row = board.cursor_row
        note.update("")
        summary = self.paint(board, self.data)
        board.move_cursor(row=min(row, max(board.row_count - 1, 0)))
        self.query_one(".read-summary", Label).update(summary)


from __future__ import annotations

from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.widgets import Input, Label

from src.tui import keys
from src.tui.screens.read_board import Board, ReadBoardPane
from src.tui.strings import t

CATALOG_PATH = "/api/v1/catalog/items"


class CatalogBoard(Board):

    BINDINGS = keys.textual_bindings(keys.CATALOG)

    def action_filter(self) -> None:
        self.parent.open_filter()  # type: ignore[union-attr]


def _local(item: dict[str, Any]) -> str:
    if item.get("untrusted"):
        return t("tui.catalog.untrusted")
    inst = item.get("installed")
    if not inst:
        return t("tui.catalog.not_installed")
    return t("tui.catalog.update") if inst.get("update_available") else t("tui.catalog.installed")


def _matches(item: dict[str, Any], needle: str) -> bool:
    card = item.get("card") or {}
    hay = " ".join(str(x) for x in (item.get("name"), item.get("kind"), item.get("publisher"),
                                    card.get("title"), card.get("brief")))
    return needle.lower() in hay.lower()


class CatalogPane(ReadBoardPane):

    path = CATALOG_PATH
    topic = "catalog"
    pane_id = "pane-catalog"
    DEFAULT_CSS = """
    CatalogPane #catalog-filter { display: none; height: 3; }
    CatalogPane.filtering #catalog-filter { display: block; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.filter_text = ""

    def compose(self) -> ComposeResult:
        yield Input(placeholder=t("tui.catalog.filter_prompt"), id="catalog-filter")
        yield from super().compose()

    def make_board(self) -> Board:
        return CatalogBoard(id="catalog-table", cursor_type="row", zebra_stripes=False)

    def setup_columns(self, board: Board) -> None:
        for col in ("name", "kind", "publisher", "version", "local", "brief"):
            board.add_column(t(f"tui.catalog.col.{col}"), key=col)

    def paint(self, board: Board, data: dict[str, Any]) -> str:
        board.clear()
        for item in [*(data.get("items") or []), *(data.get("untrusted") or [])]:
            if self.filter_text and not _matches(item, self.filter_text):
                continue
            card = item.get("card") or {}
            board.add_row(
                card.get("title") or item.get("name") or "", item.get("kind") or "", item.get("publisher") or "",
                item.get("latest") or "", _local(item), card.get("brief") or "",
                key=str(item.get("id") or id(item)),
            )
        self.query_one(".read-note", Label).update("" if board.row_count else t("tui.catalog.empty"))
        index = data.get("index") or {}
        parts = [t("tui.catalog.as_of").replace("{when}", str(index.get("as_of") or "?"))]
        if index.get("degraded"):
            parts.append(t("tui.catalog.degraded"))
        return "  ".join(parts)

    def open_filter(self) -> None:
        self.add_class("filtering")
        self.query_one("#catalog-filter", Input).focus()

    @on(Input.Changed, "#catalog-filter")
    def _filter_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value
        if self.data is not None:
            self.paint(self.query_one(Board), self.data)

    @on(Input.Submitted, "#catalog-filter")
    def _filter_commit(self) -> None:
        self.query_one(Board).focus()

    def on_key(self, event: Any) -> None:
        if event.key == "escape" and self.has_class("filtering"):
            event.stop()
            self.query_one("#catalog-filter", Input).value = ""
            self.remove_class("filtering")
            self.query_one(Board).focus()

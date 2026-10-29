
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
from textual.app import App
from textual.widgets import ContentSwitcher, Label

from src.tui.api_client import ServerUnavailable
from src.tui.app import MainScreen
from src.tui.listing_store import LIVENESS, ListingStore
from src.tui.screens.catalog import CatalogBoard
from src.tui.screens.ledger import LedgerBoard

LEDGER = {
    "accounts": [
        {"id": "a1", "name": "work", "provider": "claude", "plan": "max", "credential_state": "ok",
         "windows": [{"kind": "five_hour", "label": "5h", "used_pct": 42.4, "resets_at": "2999-01-01T00:00:00Z"},
                     {"kind": "seven_day", "label": "7d", "used_pct": 10}]},
        {"id": "a2", "name": "spare", "provider": "codex", "credential_state": "expired", "windows": [],
         "error": "login expired"},
    ],
    "total": {"accounts": 2, "windows": [{"kind": "five_hour", "label": "5h", "used_pct": 42, "accounts": 1}]},
    "loop": {"alive": False},
}


def item(name: str, kind: str, brief: str, **extra: Any) -> dict[str, Any]:
    return {"id": f"pub/{name}", "kind": kind, "name": name, "publisher": "pub", "latest": "1.0.0",
            "card": {"title": name, "brief": brief}, "fm": {}, "versions": [], **extra}


CATALOG = {
    "index": {"as_of": "2026-10-07", "degraded": True},
    "items": [item("alpha", "skill", "writes tests", installed={"update_available": False}),
              item("bravo", "theme", "dark colors", installed={"update_available": True}),
              item("charlie", "plugin", "does things")],
    "untrusted": [item("mallory", "skill", "unsigned", untrusted=True)],
}


class Harness(App[None]):

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str]] = []
        self.ledger: dict[str, Any] = LEDGER
        self.down = False
        self.listeners: list[Any] = []

        async def request(method: str, path: str, **kw: Any) -> httpx.Response:
            self.calls.append((method, path))
            if self.down:
                raise ServerUnavailable("down")
            if path == "/api/v1/provider-ledger":
                return httpx.Response(200, json=self.ledger)
            if path == "/api/v1/catalog/items":
                return httpx.Response(200, json=CATALOG)
            if path == "/api/v1/approvals":
                return httpx.Response(200, json={"items": []})
            return httpx.Response(200, json={"values": {}})

        async def fetch() -> dict[str, Any]:
            return {"stream": "s", "seq": 1, "collections": {"list": {"rows": [], "ok": True}}}

        def on_topics(fn: Any) -> Any:
            self.listeners.append(fn)
            return lambda: None

        self.client = SimpleNamespace(request=request)
        self.events = SimpleNamespace(listing=ListingStore(fetch), down=False, on_topics=on_topics,
                                      topic_pushed=lambda topic: True)

    async def on_mount(self) -> None:
        await self.push_screen(MainScreen())


def rows(table: Any) -> list[list[str]]:
    return [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]


def test_ledger_and_catalog_pilot() -> None:

    async def run() -> None:
        app = Harness()
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            assert app.screen.query_one(ContentSwitcher).current == "pane-ledger"
            ledger = app.screen.query_one(LedgerBoard)
            assert ledger.has_focus
            got = rows(ledger)
            assert [r[0] for r in got] == ["work", "spare"]
            assert got[0][4] == "5h 42%  7d 10%" and "d " in got[0][5]
            assert got[1][3] == "expired" and got[1][4] == "never read" and got[1][6] == "login expired"
            summary = str(app.screen.query_one("#pane-ledger .read-summary", Label).render())
            assert "total across 2 accounts" in summary and "5h 42%" in summary and "not running" in summary
            await pilot.press("j")
            assert ledger.cursor_row == 1
            await pilot.press("g")
            assert ledger.cursor_row == 0

            app.ledger = {**LEDGER, "accounts": LEDGER["accounts"][:1]}
            await pilot.press("G")
            for fn in app.listeners:
                fn(["provider_ledger"])
            await pilot.pause()
            await pilot.pause()
            assert [r[0] for r in rows(ledger)] == ["work"]
            n = len(app.calls)
            for fn in app.listeners:
                fn(["something_else"])
            await pilot.pause()
            assert len(app.calls) == n
            app.down = True
            for fn in app.listeners:
                fn([LIVENESS])
            await pilot.pause()
            await pilot.pause()
            assert [r[0] for r in rows(ledger)] == ["work"]
            assert "did not answer" in str(app.screen.query_one("#pane-ledger .read-note", Label).render())
            app.down = False

            await pilot.press("4")
            await pilot.pause()
            catalog = app.screen.query_one(CatalogBoard)
            assert catalog.has_focus
            got = rows(catalog)
            assert [r[0] for r in got] == ["alpha", "bravo", "charlie", "mallory"]
            assert [r[4] for r in got] == ["installed", "update available", "not installed",
                                           "untrusted publisher, cannot be installed"]
            assert "index as of 2026-10-07" in str(app.screen.query_one("#pane-catalog .read-summary", Label).render())
            await pilot.press("slash", "t", "h", "e", "m", "e")
            assert [r[0] for r in rows(catalog)] == ["bravo"]
            await pilot.press("escape")
            assert len(rows(catalog)) == 4 and catalog.has_focus
            await pilot.press("slash", "u", "n", "s", "i", "g")
            assert [r[0] for r in rows(catalog)] == ["mallory"]
            await pilot.press("enter")
            assert catalog.has_focus
            await pilot.press("G")
            assert catalog.cursor_row == catalog.row_count - 1

        assert {m for m, _ in app.calls} == {"GET"}
        assert {p for _, p in app.calls} <= {"/api/v1/provider-ledger", "/api/v1/catalog/items", "/api/v1/preferences",
                                      "/api/v1/approvals"}

    asyncio.run(run())

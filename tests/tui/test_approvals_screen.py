
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
from textual.app import App
from textual.widgets import DataTable

from src.tui import keys
from src.tui.app import MainScreen
from src.tui.listing_store import ListingStore
from src.tui.screens.approvals import ApprovalsTable, answer_request

FP = "f" * 64


def item(iid: str, **kw: Any) -> dict[str, Any]:
    return {"id": iid, "source": "dialog", "host": "local", "session_id": f"ses_{iid}", "session_name": iid,
            "kind": "permission", "question": f"run {iid}?", "options": ["Yes", "Yes, and don't ask again", "No"],
            "fingerprint": FP, **kw}


class Harness(App[None]):

    def __init__(self) -> None:
        super().__init__()
        self.items = [
            item("a1", source="agent_action", session_id="ses_t", kind="", action="stop", summary="stop session t"),
            item("d1"),
            item("q1", kind="ask_user_question", options=["Red", "Yes"]),
            item("s1", source="startup_prompt", kind="trust", options=[]),
        ]
        self.calls: list[tuple[str, str, Any]] = []
        self.post_status = 200
        self.pushed = False
        self.listeners: list[Any] = []
        snap = {"stream": "s", "seq": 1, "collections": {"list": {"rows": [], "ok": True}}}

        async def fetch() -> dict[str, Any]:
            return snap

        self.events = SimpleNamespace(
            listing=ListingStore(fetch), down=False,
            on_topics=lambda fn: (self.listeners.append(fn), lambda: None)[1],
            topic_pushed=lambda topic: self.pushed)

        async def request(method: str, path: str, **kw: Any) -> httpx.Response:
            self.calls.append((method, path, kw.get("json")))
            if path == "/api/v1/approvals":
                return httpx.Response(200, json={"items": self.items, "version": 1})
            if method == "POST":
                body = {"detail": {"reason": "dialog_changed"}} if self.post_status == 409 else {}
                return httpx.Response(self.post_status, json=body)
            return httpx.Response(200, json={"values": {}})

        self.client = SimpleNamespace(request=request)

    async def on_mount(self) -> None:
        await self.events.listing.resync()
        await self.push_screen(MainScreen())


def posts(app: Harness) -> list[tuple[str, Any]]:
    return [(p, b) for m, p, b in app.calls if m == "POST"]


def test_approvals_screen_pilot() -> None:
    async def run() -> None:
        app = Harness()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            table = app.screen.query_one(ApprovalsTable)
            assert table.has_focus and table.row_count == 4
            assert str(table.get_row_at(0)[3]) == "stop session t" and str(table.get_row_at(1)[1]) == "d1"

            await pilot.press("a")
            await pilot.pause()
            assert posts(app) == [("/api/v1/agent-actions/a1/approve", {})]
            await pilot.press("j", "d")
            await pilot.pause()
            assert posts(app)[-1] == ("/api/v1/sessions/ses_d1/dialog/answer",
                                      {"fingerprint": FP, "choice": {"dismiss": True}})
            await pilot.press("a")
            await pilot.pause()
            assert posts(app)[-1][1]["choice"] == {"option": "Yes"}

            before = len(posts(app))
            await pilot.press("j", "a")
            await pilot.press("j", "a", "d")
            await pilot.pause()
            assert len(posts(app)) == before
            assert answer_request(app.items[2], True) is None and answer_request(app.items[3], False) is None

            app.post_status = 409
            reads = sum(1 for _, p, _b in app.calls if p == "/api/v1/approvals")
            await pilot.press("g", "a")
            await pilot.pause()
            assert any("changed" in n.message for n in app._notifications)
            assert sum(1 for _, p, _b in app.calls if p == "/api/v1/approvals") > reads

            app.items = app.items[:1]
            for fn in app.listeners:
                fn(["machine_stats"])
            await pilot.pause()
            assert table.row_count == 4
            for fn in app.listeners:
                fn(["approvals"])
            await pilot.pause()
            await pilot.pause()
            assert table.row_count == 1
    asyncio.run(run())


def test_approvals_keys_come_from_the_one_table() -> None:
    bound = {(b.key, b.action) for b in ApprovalsTable.BINDINGS}
    rows = [k for k in keys.KEYS if k.scope == keys.APPROVALS]
    assert {k.action for k in rows} == {"approve", "deny"} and all(k.live for k in rows)
    for k in rows:
        for name in k.keys:
            assert (name, k.action) in bound
    assert ("j", "cursor_down") in bound and isinstance(ApprovalsTable.__mro__[1], type(DataTable))


def test_a_typed_confirmation_is_approved_only_in_the_app() -> None:
    purge = {"id": "act_p", "source": "agent_action", "confirm_text": "trader"}
    assert answer_request(purge, True) is None
    assert answer_request(purge, False) == ("/api/v1/agent-actions/act_p/deny", {})
    assert answer_request({**purge, "confirm_text": None}, True) == ("/api/v1/agent-actions/act_p/approve", {})

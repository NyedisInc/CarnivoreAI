
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from textual.app import App
from textual.widgets import ContentSwitcher, DataTable

from src.core import session_status as ss
from src.tui import keys, led
from src.tui.app import MainScreen
from src.tui.listing_store import ListingStore
from src.tui.screens.sessions import SessionsTable

REPO = Path(__file__).resolve().parents[2]


def wrap(sid: str, uuid: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"session": {"id": sid, "name": sid}, "session_uuid": uuid, "label": sid, "activity_status": status,
            "project_name": extra.pop("project", "proj"), "agent_family": extra.pop("family", "claude"),
            "unread": extra.pop("unread", False), **extra}


ROWS = [
    wrap("alpha", "u1", "idle"),
    wrap("bravo", "u2", "working", project="web"),
    wrap("charlie", "u3", "question", family="codex"),
    wrap("delta", "u4", "unknown", host_key="peer-x", host_label="studio", host_state="up"),
    wrap("echo", "u5", "asleep"),
    wrap("foxtrot", "u6", "dead"),
]
ARRANGEMENT = {"v": 1, "pinned": ["u3"], "order": ["u2", "u1"], "bands": {}, "collapsed": [], "projects_open": None}


class Harness(App[None]):

    def __init__(self) -> None:
        super().__init__()
        snap = {"stream": "s", "seq": 1, "collections": {"list": {"rows": ROWS, "ok": True}}}

        async def fetch() -> dict[str, Any]:
            return snap

        self.events = SimpleNamespace(listing=ListingStore(fetch), down=False, on_topics=lambda fn: (lambda: None),
                                      topic_pushed=lambda topic: False)

        async def request(method: str, path: str, **kw: Any) -> httpx.Response:
            if path == "/api/v1/approvals":
                return httpx.Response(200, json={"items": []})
            if path != "/api/v1/preferences":
                return httpx.Response(200, json={})
            return httpx.Response(200, json={"values": {"drawer_arrangement": ARRANGEMENT}})

        self.client = SimpleNamespace(request=request)

    async def on_mount(self) -> None:
        await self.events.listing.resync()
        await self.push_screen(MainScreen())


def names(table: DataTable[Any]) -> list[str]:
    return [str(table.get_row_at(i)[1]) for i in range(table.row_count)]


def test_sessions_screen_pilot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.tui.screens.sessions.use_ascii", lambda: False)

    async def run() -> None:
        app = Harness()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            table = app.screen.query_one(SessionsTable)
            assert names(table) == ["charlie", "bravo", "alpha", "delta", "foxtrot"]
            assert str(table.get_row_at(3)[5]) == "studio" and str(table.get_row_at(0)[5]) == ""
            assert str(table.get_row_at(0)[0]) == "‹▲›" and str(table.get_row_at(4)[0]) == " ✕ "
            assert table.get_row_at(4)[4] == "dead - process exited"

            await pilot.press("j", "j")
            assert table.cursor_row == 2
            await pilot.press("k")
            assert table.cursor_row == 1
            await pilot.press("G")
            assert table.cursor_row == 4
            await pilot.press("g")
            assert table.cursor_row == 0
            await pilot.press("down")
            assert table.cursor_row == 1

            await pilot.press("o")
            assert names(table) == ["foxtrot", "charlie", "bravo", "alpha", "delta"]
            await pilot.press("o")
            assert names(table)[0] == "charlie" and names(table)[2] == "alpha"

            await pilot.press("slash", "w", "e", "b")
            assert names(table) == ["bravo"]
            await pilot.press("enter")
            assert table.has_focus and names(table) == ["bravo"]
            await pilot.press("slash", "escape")
            assert names(table)[0] == "charlie" and len(names(table)) == 5 and table.has_focus

            switcher = app.screen.query_one(ContentSwitcher)
            for key, pane in (("2", "approvals"), ("3", "ledger"), ("4", "catalog"), ("1", "sessions")):
                await pilot.press(key)
                assert switcher.current == f"pane-{pane}"
            assert app.screen.query_one(SessionsTable).has_focus

            app.events.down = True
            app.screen.query_one("#pane-sessions").render_rows()
            assert table.get_row_at(0)[4].startswith("disconnected - no live connection")
    asyncio.run(run())


def test_led_parity_with_session_status() -> None:
    for status in ss.ALL_ACTIVITY_STATUSES:
        inner, _ = led.led_states(status)
        assert (inner == "unknown") == (status == ss.STATUS_UNKNOWN)
    assert set(ss.ACTIVITY_STATUS_PRIORITY) == ss.ALL_ACTIVITY_STATUSES
    table = [
                (dict(activity_status="dead", unread=True), "dead", "off"),
        (dict(activity_status="stopped"), "dead", "off"),
        (dict(activity_status="working", startup_gate="awaiting_startup_prompt"), "waiting-input", "active"),
        (dict(activity_status="question"), "waiting-permission", "active"),
        (dict(activity_status="notice"), "notice", "active"),
        (dict(activity_status="working_subagent", unread=True), "working", "active"),
        (dict(activity_status="running"), "working", "active"),
        (dict(activity_status="finished_unread"), "done", "unread"),
        (dict(activity_status="idle"), "idle", "steady"),
        (dict(activity_status="idle", unread=True), "done", "unread"),
        (dict(activity_status="unknown", unread=True), "unknown", "dim"),
        (dict(), "unknown", "dim"),
        (dict(activity_status="nonsense"), "unknown", "dim"),
        (dict(activity_status="working", usage_limit={"kind": "usage"}), "limit", "off"),
        (dict(activity_status="dead", usage_limit={"kind": "usage"}), "dead", "off"),
        (dict(activity_status="idle", host_key="p", host_label="studio", host_state="down"), "disconnected", "off"),
    ]
    assert led.led_for({"activity_status": "idle"}, transport="disconnected").inner == "disconnected"
    for signals, inner, outer in table:
        got = led.led_for(signals)
        assert (got.inner, got.outer) == (inner, outer), signals
    idle, unknown = led.led_for({"activity_status": "idle"}), led.led_for({})
    assert idle.hue == unknown.hue and idle.glyph() != unknown.glyph() and idle.glyph(True) != unknown.glyph(True)
    dead, dropped = led.led_for({"activity_status": "dead"}), led.led_for({}, transport="disconnected")
    assert dead.label == "dead - process exited"
    assert dropped.label == "disconnected - no live connection to this session"
    assert led.led_for({"host_key": "p", "host_label": "studio", "host_state": "down"}).label == "studio offline"
    assert led.led_for({"activity_status": "idle", "status_source": "registry"}).source == "registry"
    ts = (REPO / "web/src/lib/led.ts").read_text()
    inner_ts = re.search(r"INNER_STATES = Object\.freeze\(\[(.*?)\] as const", ts, re.S).group(1)
    for name in re.findall(r"'([a-z-]+)'", inner_ts):
        if not name.startswith("asleep"):
            assert name in led.INNER_STATES
    assert set(led.INNER_STATES) <= set(re.findall(r"'([a-z-]+)'", inner_ts))


def test_one_key_table_drives_bindings_and_help() -> None:
    bound = {(b.key, b.action) for b in SessionsTable.BINDINGS}
    for k in keys.KEYS:
        if k.scope == keys.SESSIONS:
            for name in k.keys:
                assert (name, k.action) in bound
    app_bound = {(b.key, b.action) for b in MainScreen.BINDINGS}
    assert {("1", "show_screen('sessions')"), ("4", "show_screen('catalog')")} <= app_bound
    rows = keys.help_rows()
    assert [r[0] for r in rows] == [k.label for k in keys.KEYS]
    assert all(r[1] and not r[1].startswith("tui.") for r in rows)


from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from rich.color import Color

import src.tui.app as tui_app
from src.tui import theme
from src.tui.listing_store import ListingStore


def fake_app(theme_id: str, rows: list[dict[str, Any]]) -> tui_app.CarnivoreTui:
    async def request(method: str, path: str, **kw: Any) -> httpx.Response:
        if path == "/api/v1/approvals":
            return httpx.Response(200, json={"items": []})
        if path != "/api/v1/preferences":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"values": {"theme": theme_id}})

    async def fetch() -> dict[str, Any]:
        return {"stream": "s", "seq": 1, "collections": {"list": {"rows": rows, "ok": True}}}

    async def check_session() -> bool:
        return True

    async def nothing() -> None:
        return None

    client = SimpleNamespace(request=request, check_session=check_session, aclose=nothing, base_url="http://x")
    listing = ListingStore(fetch)
    events = SimpleNamespace(
        listing=listing, down=False, on_topics=lambda fn: (lambda: None),
        topic_pushed=lambda topic: True, start=listing.resync, stop=nothing,
    )
    return tui_app.CarnivoreTui(client, events)  # type: ignore[arg-type]


def hex_of(color: Any) -> str:
    return color.hex[:7].lower()


def near(color: str, svg: str) -> bool:
    want = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    for hit in set(re.findall(r"#[0-9a-fA-F]{6}", svg)):
        got = [int(hit[i:i + 2], 16) for i in (1, 3, 5)]
        if all(abs(a - b) <= 2 for a, b in zip(want, got)):
            return True
    return False


async def paint(theme_id: str, monkeypatch: pytest.MonkeyPatch, *, colorterm: str, utf8: bool) -> dict[str, Any]:
    monkeypatch.setenv("COLORTERM", colorterm)
    monkeypatch.setattr(tui_app, "use_ascii", lambda: not utf8)
    monkeypatch.setattr("src.tui.screens.sessions.use_ascii", lambda: not utf8)
    row = {"session": {"id": "a", "name": "a"}, "session_uuid": "u1", "activity_status": "working", "tmux_session": "carnivore_a", "project_name": "p", "agent_family": "claude"}
    app = fake_app(theme_id, [row])
    async with app.run_test(size=(120, 24)) as pilot:
        for _ in range(4):
            await pilot.pause()
        screen = app.screen
        banner = screen.query_one("#server-down-banner")
        banner.display = True
        await pilot.pause()
        table = screen.query_one("#sessions-table")
        cell = table.get_row_at(0)[0]
        return {
            "palette": theme.active(),
            "theme": app.theme,
            "tabs_bg": hex_of(screen.query_one("#tabs").styles.background),
            "banner_fg": hex_of(banner.styles.color),
            "frame_type": screen.query_one("#panes").styles.border_top[0],
            "frame_color": hex_of(screen.query_one("#panes").styles.border_top[1]),
            "led": Color.parse(str(cell.style)).get_truecolor().hex,
            "glyph": cell.plain,
            "svg": app.export_screenshot(),
        }


def test_theme_palette_ascii_and_256(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def run() -> None:
        a = await paint("carnivore", monkeypatch, colorterm="truecolor", utf8=True)
        b = await paint("matrix", monkeypatch, colorterm="truecolor", utf8=True)
        for got, tid in ((a, "carnivore"), (b, "matrix")):
            pal = got["palette"]
            assert pal.theme_id == tid and got["theme"] == f"carnivore-{tid}"
            assert got["tabs_bg"] == pal.titlerow and got["banner_fg"] == pal.coral
            assert got["frame_type"] == "solid" and got["frame_color"] == pal.frame
            assert got["led"] == pal.hue("green")
            assert got["glyph"] == "‹●›"
            assert near(pal.accent, got["svg"])
        assert a["palette"].accent != b["palette"].accent and a["tabs_bg"] != b["tabs_bg"]
        assert a["palette"].coral != b["palette"].coral

        deep = await paint("matrix", monkeypatch, colorterm="", utf8=False)
        pal = deep["palette"]
        assert not pal.truecolor and pal.accent == theme.nearest_256(b["palette"].accent)
        assert deep["frame_type"] == "ascii" and deep["glyph"] == "<@>"

    asyncio.run(run())


def test_every_theme_resolves_a_palette() -> None:
    for path in sorted(theme.THEMES_DIR.glob("*/theme.json")):
        pal = theme.load_palette(path.parent.name)
        assert set(pal.hues) == set(theme.HUE_KEYS) and pal.accent.startswith("#")
    assert theme.load_palette("no-such-theme").theme_id == theme.DEFAULT_THEME
    assert json.loads((theme.THEMES_DIR / "carnivore" / "theme.json").read_text())["xterm"]

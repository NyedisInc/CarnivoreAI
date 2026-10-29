
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from src.tui.app import CarnivoreTui, MainScreen
from src.tui.events_client import EventsClient
from src.tui.listing_store import ListingStore
from src.tui.plain import plain, plain_content
from src.tui.screens import session_actions as act
from src.tui.screens.approvals import item_detail
from src.tui.screens.help import HelpScreen


def snap(seq: int) -> dict[str, Any]:
    row = {"session": {"id": "a", "name": "a"}, "activity_status": "idle"}
    return {"stream": "s", "seq": seq, "collections": {"list": {"rows": [row], "ok": True}}}


def test_start_rearms_the_auth_loss_notice() -> None:
    told: list[int] = []

    async def run() -> None:
        client = EventsClient(SimpleNamespace(), "http://x", lambda down: None, lambda: told.append(1))

        async def no_run() -> None:
            return None

        client.run = no_run  # type: ignore[method-assign]
        client._auth_lost()
        client._auth_lost()
        assert told == [1]
        client.start()
        await client._task  # type: ignore[misc]
        client._auth_lost()
        assert told == [1, 1]

    asyncio.run(run())


def test_malformed_delta_frame_resyncs_instead_of_raising() -> None:
    async def run() -> None:
        calls: list[int] = []

        async def fetch() -> dict[str, Any]:
            calls.append(1)
            return snap(1)

        store = ListingStore(fetch)
        await store.resync()
        assert store.is_live()
        bad = {"stream": "s", "seq": 2, "changes": {"list": {"upsert": [{"fields": {}}]}}}
        store.frame(bad)
        assert store._syncing is not None
        await store._syncing
        assert len(calls) == 2 and store.is_live()

    asyncio.run(run())


def test_malformed_buffered_frame_does_not_wedge_resync() -> None:
    async def run() -> None:
        async def fetch() -> dict[str, Any]:
            return snap(1)

        store = ListingStore(fetch)
        task = store.resync()
        store.frame({"stream": "s", "seq": 2, "changes": {"list": {"upsert": [{"fields": {}}]}}})
        await task
        if store._syncing is not None:
            await store._syncing
        assert store._syncing is None

    asyncio.run(run())


def test_plain_never_parses_markup() -> None:
    assert plain("[/] [@click=x]y").plain == "[/] [@click=x]y"
    assert plain(None).plain == ""


def test_approval_options_render_verbatim() -> None:
    detail = item_detail({"question": "Run [/]?", "options": ["Yes", "No"]})

    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield Static(id="box")

    async def run() -> None:
        app = Host()
        async with app.run_test() as pilot:
            box = app.query_one("#box", Static)
            box.update(plain_content(detail))
            await pilot.pause()
            assert "[Yes]  [No]" in str(box.render()) and "Run [/]?" in str(box.render())

    asyncio.run(run())


def test_session_action_paths_are_quoted() -> None:
    seen: list[str] = []

    class Client:
        async def request(self, method: str, path: str, **kw: Any) -> httpx.Response:
            seen.append(path)
            return httpx.Response(200, content=b"not json")

    asyncio.run(act.mark_read(Client(), "a/b?c#d"))
    ok, _msg = asyncio.run(act.stop(Client(), "u/../x"))
    assert seen == ["/api/v1/sessions/a%2Fb%3Fc%23d/unread", "/api/v1/sessions/u%2F..%2Fx/sleep"]
    assert ok is False


def test_relogin_keeps_one_main_screen_and_one_theme_listener() -> None:
    live: list[Any] = []

    def on_topics(fn: Any) -> Any:
        live.append(fn)
        return lambda: live.remove(fn) if fn in live else None

    async def fetch() -> dict[str, Any]:
        return snap(1)

    events = SimpleNamespace(
        listing=ListingStore(fetch), down=False, start=lambda: None, on_topics=on_topics,
        topic_pushed=lambda topic: False, stop=lambda: asyncio.sleep(0),
    )

    async def request(method: str, path: str, **kw: Any) -> httpx.Response:
        return httpx.Response(200, json={"items": [], "values": {}})

    async def check_session() -> bool:
        return True

    client = SimpleNamespace(request=request, check_session=check_session, aclose=lambda: asyncio.sleep(0),
                             base_url="http://x")

    async def run() -> None:
        app = CarnivoreTui(client, events)  # type: ignore[arg-type]
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            for _ in range(3):
                app.push_screen(HelpScreen())
                await pilot.pause()
                app.show_login()
                await pilot.pause()
                app.show_main()
                await pilot.pause()
            assert sum(isinstance(s, MainScreen) for s in app.screen_stack) == 1
            assert len(app.screen_stack) == 2
            assert sum("show_main" in getattr(f, "__qualname__", "") for f in live) == 1

    asyncio.run(run())


def test_online_attach_stops_when_the_tmux_server_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    from textual.app import App as _App

    from src.tui import attach
    from src.tui.offline.tmux_cmd import TmuxNotRunning
    from src.tui.screens.sessions import SessionsTable
    from tests.tui.test_session_actions import Harness

    ran: list[Any] = []
    monkeypatch.setattr(attach, "run", lambda plan: ran.append(plan) or 0)
    monkeypatch.setattr(attach, "socket_name", lambda: "cloude")
    monkeypatch.setattr(attach, "tmux_argv_prefix", lambda socket: ["tmux", "-L", socket])
    monkeypatch.delenv("TMUX", raising=False)

    def gone(prefix: Any, name: str, env: Any = None) -> None:
        raise TmuxNotRunning("no server running")

    monkeypatch.setattr("src.tui.screens.sessions.probe_session", gone)

    async def run() -> None:
        app = Harness()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            assert app.screen.query_one(SessionsTable).row_count == 3
            await pilot.press("enter")
            await pilot.pause()
            assert ran == []

    asyncio.run(run())

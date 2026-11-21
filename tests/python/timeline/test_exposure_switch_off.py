
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.timeline import routes as timeline_routes
from src.api.auth import require_auth
from src.core.mcp import session_events_tools, session_target, tools, write_tools
from src.core.mcp.caller import AgentCaller
from src.core.timeline import agent_tail, files, gate, reading, resolve, subscribe
from tests.python.timeline.exposure_helpers import CONV, SESSION, append, step, turn


class Manager:

    def __init__(self, infos: List[Any] | None = None) -> None:
        self.calls, self.infos = 0, infos or []

    async def list_session_infos(self) -> List[Any]:
        self.calls += 1
        return self.infos


def _client(manager: Manager) -> TestClient:
    app = FastAPI()
    app.include_router(timeline_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = manager
    return TestClient(app)


ROUTES = ("state", "events", "events/abc:main:10:0:b0010000", "turns", "threads")


def test_every_route_refuses_with_timeline_off_before_resolving_or_reading(switch, monkeypatch: pytest.MonkeyPatch) -> None:
    switch.on = False
    manager = Manager()

    def never(*_a: Any, **_k: Any) -> None:
        raise AssertionError("an off timeline read something")

    monkeypatch.setattr(files, "main_file", never)
    monkeypatch.setattr(reading, "read_forward", never)
    monkeypatch.setattr(resolve, "resolve", never)
    client = _client(manager)
    for path in ROUTES:
        answer = client.get(f"/api/v1/sessions/ses_1/timeline/{path}")
        assert answer.status_code == 409, path
        assert answer.json()["detail"]["code"] == "timeline_off", path
    assert manager.calls == 0


def test_the_hook_delivers_nothing_and_builds_no_frame_while_off(tmp_path: Path, frames, switch, monkeypatch: pytest.MonkeyPatch) -> None:
    sent, clock = frames
    switch.on = False
    got: List[Any] = []
    subscribe.subscribe(None, got.append)
    identity_reads: List[str] = []
    monkeypatch.setattr(subscribe.CONVERSATIONS, "session_of", lambda conv: identity_reads.append(conv) or SESSION)
    main = tmp_path / "proj" / f"{CONV}.jsonl"
    append(main, turn(0, "a"))
    append(main.with_suffix("") / "subagents" / "agent-a1.jsonl", [turn(1, "x")[0]])
    step(main)
    agent_tail.wake(str(main), CONV)
    clock.advance(5.0)
    assert got == [] and sent == [] and identity_reads == []
    assert agent_tail.TAILS._tails == {}  # noqa: SLF001
    switch.on = True
    gate.reset_hook_gate()
    append(main, turn(10, "b"))
    step(main)
    assert len(got) == 1 and len(sent) == 1


def _call(name: str, args: dict) -> dict:
    info = SimpleNamespace(session=SimpleNamespace(id="ses_1"), tmux_session="cloude_fixture", session_row_id=7, host_key="local")

    class View:

        app = SimpleNamespace(state=SimpleNamespace(session_manager=Manager([info])))

        async def list_session_infos(self) -> List[Any]:
            return [info]

        async def list_peer_infos(self) -> List[Any]:
            return []

    return asyncio.run(tools.call_tool(View(), AgentCaller("ses_1", "cloude_fixture", "ses_1"), name, args))


@pytest.mark.parametrize("name,args", [("session_events_list", {"target": "ses_1"}), ("session_state_get", {"target": "ses_1"})])
def test_the_mcp_tools_refuse_while_off_and_never_ask_for_an_approval(name: str, args: dict, switch, monkeypatch: pytest.MonkeyPatch) -> None:
    switch.on = False

    def no_approval(*_a: Any, **_k: Any) -> None:
        raise AssertionError("a read tool asked for an approval")

    monkeypatch.setattr(write_tools, "park", no_approval)
    monkeypatch.setattr(session_target, "_session_uuid_of_row", lambda row_id: SESSION)
    monkeypatch.setattr(resolve, "resolve", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("resolved while off")))
    result = _call(name, args)
    assert result.get("isError") is True
    assert "session timeline is off" in result["content"][0]["text"]
    assert name in session_events_tools.READ_TOOLS and name not in tools.WRITE_TOOLS


from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import pytest

from src.core.timeline import agent_tail, ctx_cache, gate, hot, subscribe
from src.core.timeline.context import ExtractContext
from src.core.timeline.extract import extract_line
from src.core.timeline.model import FILE_KEY_MAIN, TimelineEvent
from src.core.timeline.push import FrameCoalescer
from tests.python.timeline.exposure_helpers import CONV, SESSION, Clock, Switch

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "timeline"
UNKNOWN_FIXTURE = "unknown_kinds"


@pytest.fixture(scope="session")
def manifest() -> Dict[str, Dict[str, Any]]:
    return json.loads((FIXTURES / "MANIFEST.json").read_text())


def read_fixture(entry: Dict[str, Any]) -> Iterator[Tuple[bytes, int]]:
    offset = 0
    for raw in (FIXTURES / entry["file"]).read_bytes().splitlines(keepends=True):
        offset += len(raw)
        yield raw.rstrip(b"\n"), offset


def file_key_of(entry: Dict[str, Any]) -> str:
    path = Path(entry["file"])
    return path.stem.removeprefix("agent-") if path.parent.name == "subagents" else FILE_KEY_MAIN


def run_fixture(entry: Dict[str, Any]) -> List[Tuple[Dict[str, Any], List[TimelineEvent]]]:
    conv = Path(entry["file"]).parts[0].removesuffix(".jsonl")
    ctx = ExtractContext(conv=conv, file_key=file_key_of(entry))
    return [(json.loads(raw), extract_line(ctx, raw, end)) for raw, end in read_fixture(entry)]


@pytest.fixture
def switch(monkeypatch: pytest.MonkeyPatch) -> Switch:
    flag = Switch()
    monkeypatch.setattr(gate, "switch_on", lambda: flag.on)
    monkeypatch.setattr(agent_tail.AgentTails, "worker_enabled", False)
    monkeypatch.setattr(agent_tail.TAILS, "worker_enabled", False, raising=False)
    monkeypatch.setattr(subscribe.CONVERSATIONS, "session_of", lambda conv: SESSION if conv == CONV else None)
    gate.reset_hook_gate()
    _clean()
    yield flag
    gate.reset_hook_gate()
    _clean()


def _clean() -> None:
    subscribe.reset_for_tests()
    ctx_cache.clear()
    agent_tail.TAILS.clear()
    hot.DRIVER.clear()
    hot.reset_gate()


@pytest.fixture
def frames(monkeypatch: pytest.MonkeyPatch, switch: Switch) -> Tuple[List[Dict[str, Any]], Clock]:
    sent: List[Dict[str, Any]] = []
    clock = Clock()
    monkeypatch.setattr(subscribe, "PUSH", FrameCoalescer(lambda frame: sent.append(frame) or True, clock.now, clock.later))
    return sent, clock


@pytest.fixture
def api(tmp_path: Path, switch, monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.timeline import routes as timeline_routes
    from src.api.auth import require_auth
    from src.core.bookmarks import rows
    from src.core.session_timeline import gather
    from src.core.timeline import files, resolve, service

    main = tmp_path / "proj" / f"{CONV}.jsonl"
    row = SimpleNamespace(session_uuid=SESSION, claude_session_uuid=CONV, working_dir=str(tmp_path), agent_type="claude")

    async def fake_resolve(_manager: Any, key: str, listing: Any = None) -> Any:
        return resolve.Resolved(row, None)

    monkeypatch.setattr(resolve, "resolve", fake_resolve)
    monkeypatch.setattr(rows, "family_of", lambda agent: "claude")
    monkeypatch.setattr(files, "main_file", lambda conv, cwd: str(main.resolve()))
    monkeypatch.setattr(service, "_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(gather, "conversations_of", lambda key: (row, [CONV]))
    app = FastAPI()
    app.include_router(timeline_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = SimpleNamespace()
    return TestClient(app), main



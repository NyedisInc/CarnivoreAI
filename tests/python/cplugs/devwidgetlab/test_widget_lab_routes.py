
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.devwidgetlab import capture, errors
from src.cplugs.devwidgetlab.drafts import store
from src.cplugs.host import developer_mode, runtime
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/devwidgetlab"
REQUEST = {"widget": "core.notes", "host": "home", "size": "m", "theme": "carnivore", "fixture": "data", "state": "normal", "scenario": None}


@pytest.fixture
def host_app(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    app.include_router(__import__("src.cplugs.host.routes", fromlist=["router"]).router, prefix="/api/v1")
    return app, host


def test_ships_off_and_refuses_without_a_token_and_while_off(host_app) -> None:
    app, host = host_app
    manifest = runtime.find("devwidgetlab").manifest
    assert manifest.default_enabled is False and manifest.tier == "dev"
    with TestClient(app) as anonymous:
        assert anonymous.get(f"{BASE}/status").status_code == 401
        assert anonymous.post(f"{BASE}/capture", json=REQUEST).status_code == 401
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        off = client.get(f"{BASE}/status")
        assert off.status_code == 409 and off.json()["detail"]["code"] == "cplug_disabled"
        assert client.post(f"{BASE}/capture", json=REQUEST).status_code == 409
        turn_on(host, "devwidgetlab")
        assert client.get(f"{BASE}/status").status_code == 200


def test_a_dev_tier_plugin_reads_as_off_without_developer_mode(host_app, monkeypatch) -> None:
    app, host = host_app
    turn_on(host, "devwidgetlab")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        assert client.get(f"{BASE}/status").status_code == 200
        monkeypatch.setattr(developer_mode, "is_on", lambda: False)
        refused = client.get(f"{BASE}/status")
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "cplug_disabled"


def test_status_says_whether_a_capture_can_run_and_why_not(host_app, monkeypatch) -> None:
    app, host = host_app
    turn_on(host, "devwidgetlab")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        monkeypatch.setattr(store, "SCRIPT", Path("/nonexistent/capture_one.py"))
        gone = client.get(f"{BASE}/status").json()
        assert gone["available"] is False and gone["reason"] == "no_checkout"
        monkeypatch.setattr(store, "SCRIPT", store.REPO / "scripts" / "widgets" / "capture_one.py")
        monkeypatch.setattr(capture.importlib.util, "find_spec", lambda name: None)
        no_pw = client.get(f"{BASE}/status").json()
        assert no_pw["available"] is False and no_pw["reason"] == "no_playwright"
        assert no_pw["captures_dir"].endswith("captures")


@pytest.mark.parametrize("override", [
    {"widget": "core.notes; rm -rf /"}, {"widget": "../x"}, {"widget": ""}, {"host": "kitchen"}, {"size": "M!"}, {"size": ""},
    {"theme": "a b"}, {"fixture": "random"}, {"state": "open"}, {"extra": 1}, {"scenario": "x" * (capture.MAX_SCENARIO_CHARS + 1)},
])
def test_a_bad_request_is_refused_before_any_process_starts(host_app, monkeypatch, override) -> None:
    app, host = host_app
    turn_on(host, "devwidgetlab")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    started: List[Any] = []

    async def spawn(*args: Any, **kwargs: Any):
        started.append(args)
        raise AssertionError("a process must not start")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with TestClient(app) as client:
        assert client.post(f"{BASE}/capture", json={**REQUEST, **override}).status_code == 422
    assert started == []


def test_the_command_is_an_argument_list_with_every_choice_in_its_own_slot(tmp_path: Path) -> None:
    out = tmp_path / "o"
    args = capture.command_for(REQUEST, out, tmp_path / "s.json")
    assert args[1:3] == ["-m", "scripts.widgets.capture_one"]
    pairs = dict(zip(args[3::2], args[4::2]))
    assert pairs == {"--widget": "core.notes", "--host": "home", "--size": "m", "--theme": "carnivore", "--fixture": "data", "--state": "normal",
                     "--out": str(out), "--scenario-file": str(tmp_path / "s.json")}
    assert "--scenario-file" not in capture.command_for(REQUEST, out, None)


def test_a_capture_that_did_not_run_or_did_not_pass_is_never_ok() -> None:
    clean = json.dumps({"ok": True, "failures": []})
    assert capture.result_from(clean, 0, "")["ok"] is True
    assert capture.result_from(clean, 1, "")["ok"] is False
    assert capture.result_from(json.dumps({"ok": False, "failures": ["x"]}), 0, "")["ok"] is False
    unknown = capture.result_from("", 2, "capture_one: CANNOT DETERMINE - playwright is not installed in this venv\n")
    assert unknown["ok"] is False and unknown["determined"] is False and "CANNOT DETERMINE" in unknown["failures"][0]
    assert capture.result_from("not json", 0, "")["ok"] is False
    assert capture.result_from("", 0, "")["ok"] is False


class FakeProc:

    def __init__(self, out: str, code: int = 0, hang: bool = False) -> None:
        self.out, self.returncode, self.hang, self.killed = out, code, hang, False

    async def communicate(self):
        if self.hang:
            await asyncio.sleep(60)
        return self.out.encode(), b""

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


def test_run_capture_writes_the_scenario_beside_the_capture_and_reads_the_answer(tmp_path: Path, monkeypatch) -> None:
    seen: List[Any] = []

    async def spawn(*args: Any, **kwargs: Any):
        seen.append((args, kwargs))
        return FakeProc(json.dumps({"ok": True, "failures": [], "png": {"path": "/x.png", "pixels": [1, 1]}}))

    monkeypatch.setattr(capture, "availability", lambda: {"available": True, "reason": ""})
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    result = asyncio.run(capture.run_capture({**REQUEST, "scenario": '{"GET /x": 1}'}, tmp_path))
    assert result["ok"] is True and result["determined"] is True
    args, kwargs = seen[0]
    scenario_path = Path(args[args.index("--scenario-file") + 1])
    assert scenario_path.read_text() == '{"GET /x": 1}' and scenario_path.is_relative_to(tmp_path / "captures")
    assert kwargs["cwd"] == str(capture.REPO)


def test_a_capture_with_no_checkout_is_refused_not_passed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(store, "SCRIPT", tmp_path / "missing.py")
    with pytest.raises(errors.CaptureUnavailable):
        asyncio.run(capture.run_capture(REQUEST, tmp_path))


def test_a_second_capture_while_one_runs_is_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(capture, "availability", lambda: {"available": True, "reason": ""})

    async def spawn(*args: Any, **kwargs: Any):
        return FakeProc(json.dumps({"ok": True, "failures": []}))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def both() -> None:
        async with capture._running:
            with pytest.raises(errors.CaptureBusy):
                await capture.run_capture(REQUEST, tmp_path)

    asyncio.run(both())


def test_a_capture_past_its_limit_is_stopped(tmp_path: Path, monkeypatch) -> None:
    proc = FakeProc("", hang=True)

    async def spawn(*args: Any, **kwargs: Any):
        return proc

    monkeypatch.setattr(capture, "availability", lambda: {"available": True, "reason": ""})
    monkeypatch.setattr(capture, "TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(errors.CaptureTimeout):
        asyncio.run(capture.run_capture(REQUEST, tmp_path))
    assert proc.killed is True


def test_capture_uses_the_same_checkout_lookup_as_the_drafts(tmp_path: Path, monkeypatch) -> None:
    from src.cplugs.devwidgetlab.drafts import checkout

    monkeypatch.setattr(checkout, "resolve", lambda storage_path=None: None)
    assert capture.availability() == {"available": False, "reason": "no_checkout"}
    monkeypatch.setattr(checkout, "resolve", lambda storage_path=None: tmp_path)
    monkeypatch.setattr(capture.importlib.util, "find_spec", lambda name: object())
    assert capture.availability()["available"] is True and capture.repo_root() == tmp_path

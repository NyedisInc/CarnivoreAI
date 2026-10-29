
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.devwidgetlab import capture, matrix
from src.cplugs.devwidgetlab.drafts import store
from src.cplugs.host import developer_mode, runtime
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/devwidgetlab"


@pytest.fixture
def lab(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    app.include_router(__import__("src.cplugs.host.routes", fromlist=["router"]).router, prefix="/api/v1")
    turn_on(host, "devwidgetlab")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    monkeypatch.setattr(matrix, "_job", {"task": None, "started": None, "exit": None, "reason": ""})
    with TestClient(app) as client:
        yield client, tmp_path / "cplugs" / "devwidgetlab"


def test_the_routes_need_a_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    app = FastAPI()
    runtime.install(app, tmp_path)
    app.include_router(__import__("src.cplugs.host.routes", fromlist=["router"]).router, prefix="/api/v1")
    with TestClient(app) as anonymous:
        assert anonymous.get(f"{BASE}/fit-table").status_code == 401
        assert anonymous.post(f"{BASE}/matrix", json={}).status_code == 401


def test_no_run_means_no_table_and_a_broken_file_is_no_table(lab) -> None:
    client, storage = lab
    first = client.get(f"{BASE}/fit-table").json()
    assert first["table"] is None and first["running"] is False and first["exit"] is None
    (storage / "matrix").mkdir(parents=True, exist_ok=True)
    (storage / "matrix" / "fit-table.json").write_text("{not json", encoding="utf-8")
    assert client.get(f"{BASE}/fit-table").json()["table"] is None
    (storage / "matrix" / "fit-table.json").write_text(json.dumps({"schema": 1, "widgets": []}), encoding="utf-8")
    assert client.get(f"{BASE}/fit-table").json()["table"]["schema"] == 1


def test_a_run_needs_a_checkout_and_playwright(lab, monkeypatch) -> None:
    client, _ = lab
    monkeypatch.setattr(store, "SCRIPT", Path("/nonexistent/capture_one.py"))
    refused = client.post(f"{BASE}/matrix", json={})
    assert refused.status_code == 503 and refused.json()["detail"]["code"] == "capture_unavailable"


def test_the_command_is_an_argument_list(tmp_path: Path) -> None:
    args = matrix.command_for(tmp_path, False)
    assert args[1:3] == ["-m", "scripts.widgets.gate"] and args[3:] == ["--out", str(tmp_path)]
    assert matrix.command_for(tmp_path, True)[-1] == "--catalog"


def test_one_widget_run_gates_only_that_widget(tmp_path: Path) -> None:
    args = matrix.command_for(tmp_path, False, "core.notes")
    assert args[3:] == ["--out", str(tmp_path), "--only", "core.notes"]
    assert matrix.command_for(tmp_path, True, "core.analytics:vitals")[3:] == ["--out", str(tmp_path), "--only", "core.analytics", "--catalog"]
    assert "--only" not in matrix.command_for(tmp_path, False, None)


def test_the_route_takes_only_a_key_and_needs_the_token(lab, monkeypatch) -> None:
    client, _ = lab
    monkeypatch.setattr(matrix, "availability", lambda: {"available": True, "reason": ""})
    spawned: List[Any] = []

    class Proc:
        returncode = 0

        async def wait(self) -> int:
            return 0

    async def spawn(*args: Any, **kwargs: Any) -> Proc:
        spawned.append(args)
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    assert client.post(f"{BASE}/matrix", json={"only": "../etc/passwd"}).status_code == 422
    assert client.post(f"{BASE}/matrix", json={"only": "core.notes"}).status_code == 200
    client.get(f"{BASE}/fit-table")
    assert spawned[0][-2:] == ("--only", "core.notes")


def test_a_second_run_is_refused_while_one_is_going_and_the_exit_is_kept(lab, monkeypatch) -> None:
    client, _ = lab
    monkeypatch.setattr(matrix, "availability", lambda: {"available": True, "reason": ""})
    spawned: List[Any] = []

    class Proc:
        returncode = 1

        async def wait(self) -> int:
            await asyncio.sleep(0.2)
            return 1

    async def spawn(*args: Any, **kwargs: Any) -> Proc:
        spawned.append(args)
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    started = client.post(f"{BASE}/matrix", json={"catalog": True})
    assert started.status_code == 200 and started.json()["running"] is True
    busy = client.post(f"{BASE}/matrix", json={})
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "capture_busy"
    assert "--catalog" in spawned[0]
    assert client.post(f"{BASE}/matrix", json={"bogus": 1}).status_code == 422

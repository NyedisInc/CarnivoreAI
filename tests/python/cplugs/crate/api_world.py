
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.crate import routes, service
from src.cplugs.crate.jobs import runner, state
from src.cplugs.host import runtime
from tests.python.cplugs.crate.crate_world import env_for, make_world
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/crate"
JOIN_S = 120.0


class ApiWorld:

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, on: bool = True, **settings: Any) -> None:
        self.world: SimpleNamespace = make_world(tmp_path)
        self.settings: Dict[str, Any] = dict(settings)
        self.app = FastAPI()
        self.app.include_router(routes.router, prefix="/api/v1")
        host_dir = tmp_path / "host"
        host_dir.mkdir()
        self.host = runtime.install(self.app, host_dir)
        self.published: List[str] = []
        self.host.publish = self.published.append
        if on:
            turn_on(self.host, "crate")
        monkeypatch.setattr(service, "env_of", lambda ctx: self.env)

    @property
    def env(self) -> Any:
        return env_for(self.world, **self.settings)

    @property
    def ctx(self) -> Any:
        return self.host.context("crate")

    def client(self, *, authed: bool = True) -> TestClient:
        if authed:
            self.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
        else:
            self.app.dependency_overrides.pop(require_auth, None)
        return TestClient(self.app)

    def jobs_root(self) -> Path:
        return state.jobs_dir(self.env.work)


def wait_job(api: ApiWorld, job_id: str) -> state.JobRecord:
    assert runner.join(JOIN_S), f"job {job_id} did not end in {JOIN_S} s"
    return state.load(api.jobs_root(), job_id)


def stop_runner() -> None:
    runner.cancel_all()
    runner.join(JOIN_S)


def export(api: ApiWorld, client: TestClient, body: Dict[str, Any]) -> state.JobRecord:
    planned = client.post(f"{BASE}/plan", json=body)
    assert planned.status_code == 200 and planned.json()["ok"], planned.text
    started = client.post(f"{BASE}/exports", json={**body, "fingerprint": planned.json()["fingerprint"]})
    assert started.status_code == 202, started.text
    return wait_job(api, started.json()["job_id"])

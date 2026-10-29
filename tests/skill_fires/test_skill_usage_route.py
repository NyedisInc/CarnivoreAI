
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import skill_usage_routes
from src.api.auth import require_auth
from src.core.skill_fires.scan import scan_file
from src.core.skill_fires.store import SkillFireStore


def _slash(name: str, when: datetime) -> str:
    stamp = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    return ('{"type":"user","timestamp":"%s","message":{"role":"user","content":'
            '"<command-name>/%s</command-name>"}}' % (stamp, name))


def _client(store: SkillFireStore, monkeypatch, authed: bool) -> TestClient:
    monkeypatch.setattr(skill_usage_routes, "default_store", lambda: store)
    app = FastAPI()
    app.include_router(skill_usage_routes.router, prefix="/api/v1")
    if authed:
        app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def test_windows_count_and_never_scanned_is_not_zero(tmp_path: Path, monkeypatch) -> None:
    store = SkillFireStore(tmp_path / "skill_fires.db")
    client = _client(store, monkeypatch, True)
    empty = client.get("/api/v1/skill-fires/usage", params={"skill": "deploy"}).json()
    assert empty["state"] == "not_measured" and empty["fired_30d"] is None
    now = datetime.now(timezone.utc)
    transcript = tmp_path / "c.jsonl"
    transcript.write_text("\n".join([
        _slash("deploy", now - timedelta(days=2)), _slash("deploy", now - timedelta(days=20)),
        _slash("deploy", now - timedelta(days=60)), _slash("other", now)]) + "\n")
    scan_file(store, str(transcript), "claude", "default")
    got = client.get("/api/v1/skill-fires/usage", params={"skill": "deploy"}).json()
    assert (got["state"], got["fired_7d"], got["fired_30d"], got["fired_90d"]) == ("measured", 1, 2, 3)
    unfired = client.get("/api/v1/skill-fires/usage", params={"skill": "nope"}).json()
    assert unfired["state"] == "measured" and unfired["fired_90d"] == 0


def test_route_requires_auth(tmp_path: Path, monkeypatch) -> None:
    client = _client(SkillFireStore(tmp_path / "s.db"), monkeypatch, False)
    assert client.get("/api/v1/skill-fires/usage", params={"skill": "x"}).status_code in (401, 403)

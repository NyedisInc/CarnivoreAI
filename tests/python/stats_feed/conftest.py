
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.stats_feed_routes import router
from src.core.stats import config, wiring
from src.core.stats.store import StatsStore
from src.core.stats_feed import StatsFeed
from tests.stats import seed

CONV = "f597fe41-5c73-4dc1-8bcc-9b463c797210"
NOW = int(time.time()) // 60 * 60 + 30


def line(t: float, mid: str, *, fresh: int, write: int, read: int, out: int) -> str:
    stamp = datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")
    return json.dumps({"type": "assistant", "timestamp": stamp, "cwd": "/tmp/project", "sessionId": CONV, "message": {
        "id": mid, "model": "claude-sonnet-4-6", "usage": {
            "input_tokens": fresh, "cache_creation_input_tokens": write, "cache_read_input_tokens": read,
            "output_tokens": out}}}) + "\n"


class Env:

    def __init__(self, tmp_path: Path) -> None:
        self.dir = tmp_path
        self.store = StatsStore(tmp_path)
        wiring.initialize(self.store)
        config.update_settings(self.store, enabled=True, revision=config.get_settings(self.store)["revision"])
        self.clock = [0.0]
        self.notified: list = []

    def deliver(self, lines: list, name: str = "t") -> None:
        path = self.dir / f"{name}.jsonl"
        path.write_text("".join(lines))
        seed.deliver(self.dir, path, family="claude", conversation_id=CONV)

    def feed(self, **kw) -> StatsFeed:
        args = dict(store_for=lambda: self.store, state_dir=self.dir, db_path=self.dir / "cloude.db",
                    notify=lambda *a: self.notified.append(a), wall=lambda: NOW, clock=lambda: self.clock[0])
        return StatsFeed(**{**args, **kw})

    def client(self, feed: StatsFeed) -> TestClient:
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.state.stats_feed = feed
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
        return TestClient(app)


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)

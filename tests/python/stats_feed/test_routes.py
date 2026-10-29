
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.stats_feed_routes import router
from tests.python.stats_feed.conftest import NOW, line


def test_auth_required_and_bad_window_is_422(env):
    assert TestClient(_bare(env)).get("/api/v1/stats/feed").status_code in (401, 403)
    client = env.client(env.feed())
    assert client.get("/api/v1/stats/feed", params={"window": "2h"}).status_code == 422


def _bare(env) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.stats_feed = env.feed()
    return app


def test_lease_false_starts_nothing_and_mcp_matches_the_route(env):
    from src.core.mcp.read_tools import TOOLS

    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    feed = env.feed()
    client = env.client(feed)
    plain = client.get("/api/v1/stats/feed", params={"window": "1h", "lease": "false"}).json()
    assert not feed.leased() and not feed.running and env.notified == []

    async def call():
        manager = SimpleNamespace(app=SimpleNamespace(state=client.app.state))
        return await TOOLS["stats_feed"][3](manager, None, {"window": "1h"})

    result = asyncio.run(call())
    text = result["content"][0]["text"] if isinstance(result, dict) and "content" in result else json.dumps(result)
    doc = json.loads(text)
    assert doc["totals"] == plain["totals"] == {"fresh": 4, "cache_write": 5, "cache_read": 6, "out": 7}
    assert doc["in"] == plain["in"] and doc["state"] == plain["state"] and "diagnostics" in doc
    assert not feed.leased()


def test_the_feed_route_takes_the_owner_only_never_a_peer_token():
    from fastapi.dependencies.models import Dependant

    def calls(dep: Dependant):
        yield dep.call
        for sub in dep.dependencies:
            yield from calls(sub)

    feed_routes = [r for r in router.routes if r.path.endswith("/feed")]
    assert feed_routes
    for route in feed_routes:
        held = [c for c in calls(route.dependant) if c is not None]
        assert any(c.__name__ == "require_auth" for c in held)
        assert not any(hasattr(c, "peer_scope") for c in held)

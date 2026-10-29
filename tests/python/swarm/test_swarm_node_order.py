
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.api import swarm_node_order_routes as routes
from src.core.mcp import swarm_order_tools, tools
from src.core.swarm import node_order


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str]]:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"keep": 1}))
    monkeypatch.setattr(routes, "_config_path", lambda: path)
    named: list[str] = []
    monkeypatch.setattr("src.core.resource_push.notify", named.append)
    return path, named


def test_a_tier_write_persists_reloads_and_names_the_push(config: tuple[Path, list[str]]) -> None:
    path, named = config
    keys = ["session:9f3c2a10-1111-2222-3333-444455556666", "agent:7", "project:3"]
    stored = asyncio.run(routes.put_node_order(routes.NodeOrderWrite(tier="agents", keys=keys)))
    assert stored == {"companies": [], "projects": [], "agents": keys}
    asyncio.run(routes.put_node_order(routes.NodeOrderWrite(tier="companies", keys=["company:2", "company:1"])))
    assert asyncio.run(routes.get_node_order()) == {"companies": ["company:2", "company:1"], "projects": [], "agents": keys}
    doc = json.loads(path.read_text())
    assert doc["keep"] == 1 and doc[node_order.ORDER_KEY]["agents"] == keys
    assert named == ["swarm_node_order", "swarm_node_order"]


@pytest.mark.parametrize("keys", [["agent:7", "agent:7"], ["cloude_myproject"], ["session:../../etc"], ["agent:7 x"]])
def test_a_bad_or_repeated_key_is_refused_and_nothing_is_written(config: tuple[Path, list[str]], keys: list[str]) -> None:
    path, named = config
    with pytest.raises(HTTPException) as refused:
        asyncio.run(routes.put_node_order(routes.NodeOrderWrite(tier="agents", keys=keys)))
    assert refused.value.status_code == 422
    assert json.loads(path.read_text()) == {"keep": 1} and named == []


def test_the_mcp_tools_are_registered_and_the_write_is_a_write(config: tuple[Path, list[str]]) -> None:
    assert "swarm_node_order" in tools._TOOLS and "swarm_set_node_order" in tools.WRITE_TOOLS
    assert "swarm_node_order" not in tools.WRITE_TOOLS
    out = asyncio.run(swarm_order_tools.swarm_set_node_order(None, None, {"tier": "projects", "keys": ["project:4"]}))
    assert json.loads(out["content"][0]["text"])["projects"] == ["project:4"]
    with pytest.raises(swarm_order_tools.ToolError):
        asyncio.run(swarm_order_tools.swarm_set_node_order(None, None, {"tier": "sysop", "keys": []}))

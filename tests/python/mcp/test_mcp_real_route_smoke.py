
from __future__ import annotations

import asyncio
import importlib
import json
import pkgutil
from types import SimpleNamespace

import pytest

from src.core.federation import peer_fanout
import src.core.mcp as mcp_pkg
from src.core.mcp import route_adapters as ra, tools
from tests.python.mcp.test_mcp_route_adapters import PANE, READ_ONLY, View
from tests.python.project_history.test_projects_history_route import seeded  # noqa: F401


def _call(name: str, args: dict, caller=PANE) -> dict:
    return asyncio.run(tools.call_tool(View(), caller, name, args))


def _answer(result: dict) -> dict:
    assert not result.get("isError"), result
    return json.loads(result["content"][0]["text"])


def test_project_history_get_runs_the_real_route(seeded):  # noqa: F811
    for caller in (PANE, READ_ONLY):
        body = _answer(_call("project_history_get", {"limit": 5, "session_limit": 5}, caller))
        assert body["state"] == "ok" and body["total"] >= 1


def test_history_filters_reach_the_paired_computers(seeded, monkeypatch):  # noqa: F811
    asked: list = []

    async def ask(path, open_db, *a, **k):
        asked.append(path)
        return []

    monkeypatch.setattr(peer_fanout, "ask_peers", ask)
    _answer(_call("project_history_get", {"q": "alpha", "state": "running", "include_empty": False, "limit": 5}))
    (path,) = asked
    assert path.startswith("/projects/history?")
    query = dict(p.split("=") for p in path.split("?", 1)[1].split("&"))
    assert query == {"q": "alpha", "state": "running", "include_empty": "false", "limit": "5"}


class _StrictRequest(SimpleNamespace):

    misses: list = []

    def __getattr__(self, name: str):
        type(self).misses.append(name)
        raise AttributeError(name)


def _read_specs() -> list:
    found = []
    for info in pkgutil.iter_modules(mcp_pkg.__path__):
        module = importlib.import_module(f"src.core.mcp.{info.name}")
        found += [s for s in getattr(module, "SPECS", ()) if isinstance(s, ra.RouteTool) and s.gate == ra.READ]
    return found


@pytest.mark.parametrize("spec", _read_specs(), ids=lambda s: s.name)
def test_no_read_route_asks_the_stand_in_for_what_it_lacks(spec, seeded, monkeypatch):  # noqa: F811
    _StrictRequest.misses = []
    real = ra.route_request
    monkeypatch.setattr(ra, "route_request", lambda manager, query=None: _StrictRequest(**vars(real(manager, query))))
    args = {"target": "cloude_b", **spec.example} if spec.reach else dict(spec.example)
    _call(spec.name, args)
    assert _StrictRequest.misses == [], f"{spec.name} read request.{_StrictRequest.misses[0]}, which the stand-in does not have"

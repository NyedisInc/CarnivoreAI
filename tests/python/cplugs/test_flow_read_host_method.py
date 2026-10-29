
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.cplugs.host import flow_port
from src.cplugs.host.activity_reader import ActivityReader
from src.cplugs.runtime import frames, guards
from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.cplugs.runtime.owner_tokens import OwnerTokens
from tests.python.cplugs.flow import fixture as fx


class Clock:

    now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def dispatcher(tmp_path, monkeypatch, clock):
    made = fx.make_install(tmp_path)
    monkeypatch.setattr(ActivityReader, "_transcript_path", lambda self, conv: next((str(p) for p in made["paths"].values() if p.stem == conv), None))
    port = flow_port.FlowPort(lambda: made["state_dir"], cache=flow_port.PartCache(clock))
    services = HostServices(activity=lambda row: None, flow_run=port.run, flow_run_part=port.part)
    return HostDispatcher(services, OwnerTokens())


def _ctx(tmp_path: Path, *granted: str, key: str = "k") -> PluginContext:
    return PluginContext(plugin_id="flowx", install_key=key, data_dir=tmp_path / "d", granted=frozenset(granted), tier="sideload")


def _call(dispatcher: HostDispatcher, ctx: PluginContext, params: dict, method: str = "flow.run"):
    try:
        return asyncio.run(dispatcher.handle(ctx, method, params))
    except guards.Refused as exc:
        return exc


def test_flow_read_returns_the_run_and_no_grant_is_refused(dispatcher, tmp_path):
    answer = _call(dispatcher, _ctx(tmp_path, "flow.read"), {"seed": "huddle_item", "id": "395"})
    run = answer["run"]
    assert {"lanes", "blocks", "edges", "marks", "events", "idle_gaps", "stats", "warnings", "sources", "seed"} <= set(run)
    assert not {"says", "calls", "snapshot"} & set(run)
    assert run["seed"]["id"] == "395" and any(l["id"].startswith("s:") for l in run["lanes"])
    refused = _call(dispatcher, _ctx(tmp_path, "sessions.read"), {"id": "395"})
    assert isinstance(refused, guards.Refused) and refused.code == "not_granted" and refused.data == {"permission": "flow.read"}
    assert _call(dispatcher, _ctx(tmp_path, "sessions.read"), {"token": "x", "index": 0}, "flow.run_part").code == "not_granted"


def test_a_big_run_comes_back_in_parts_that_join_to_the_exact_json(dispatcher, tmp_path, monkeypatch, clock):
    ctx = _ctx(tmp_path, "flow.read")
    inline = _call(dispatcher, ctx, {"id": "395"})["run"]
    monkeypatch.setattr(flow_port, "INLINE_MAX", 3000)
    monkeypatch.setattr(flow_port, "PART_BUDGET", 3000)
    paged = _call(dispatcher, ctx, {"id": "395"})
    assert set(paged) == {"token", "parts", "bytes"} and paged["parts"] > 1
    texts = [_call(dispatcher, ctx, {"token": paged["token"], "index": i}, "flow.run_part")["text"] for i in range(paged["parts"])]
    assert all(len(json.dumps(t)) <= 3000 for t in texts) and len("".join(texts)) == paged["bytes"]
    assert json.loads("".join(texts)) == inline
    assert _call(dispatcher, ctx, {"token": paged["token"], "index": paged["parts"]}, "flow.run_part").code == "invalid_params"
    assert _call(dispatcher, _ctx(tmp_path, "flow.read", key="other"), {"token": paged["token"], "index": 0}, "flow.run_part").code == "not_found"
    clock.now += flow_port.CACHE_TTL_S + 1
    assert _call(dispatcher, ctx, {"token": paged["token"], "index": 0}, "flow.run_part").code == "not_found"
    assert _call(dispatcher, ctx, {"token": "nope", "index": 0}, "flow.run_part").code == "not_found"


def test_cache_keeps_three_per_install(dispatcher, tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "flow.read")
    monkeypatch.setattr(flow_port, "INLINE_MAX", 3000)
    monkeypatch.setattr(flow_port, "PART_BUDGET", 3000)
    tokens = [_call(dispatcher, ctx, {"id": "395"})["token"] for _ in range(4)]
    assert _call(dispatcher, ctx, {"token": tokens[0], "index": 0}, "flow.run_part").code == "not_found"
    assert _call(dispatcher, ctx, {"token": tokens[3], "index": 0}, "flow.run_part")["index"] == 0


def test_unknown_seed_bad_params_and_the_hard_cap_are_refused(dispatcher, tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "flow.read")
    assert _call(dispatcher, ctx, {"id": "999999"}).code == "not_found"
    assert _call(dispatcher, ctx, {"id": ""}).code == "invalid_params"
    assert _call(dispatcher, ctx, {"id": "395", "seed": "nope"}).code == "invalid_params"
    monkeypatch.setattr(flow_port, "HARD_MAX", 2000)
    big = _call(dispatcher, ctx, {"id": "395"})
    assert big.code == "too_large" and big.data["bytes"] > big.data["limit"]


def test_quote_heavy_parts_stay_under_the_frame_limit_and_join_exactly():
    text = json.dumps({"x": ['"q\\"' * 400000, "plain" * 100000]}, separators=(",", ":"))
    assert len(json.dumps(text)) > 1.3 * len(text) and len(text) > 2_000_000
    parts = flow_port.cut_parts(text)
    assert len(parts) > 3 and "".join(parts) == text
    for i, part in enumerate(parts):
        assert len(frames.result_reply(7, {"index": i, "text": part})) <= frames.MAX_FRAME_BYTES
    assert flow_port.cut_parts("") == [""]


def test_the_cache_sweeps_every_install_and_forgets_a_stopped_one(clock):
    cache = flow_port.PartCache(clock)
    old = cache.put("a", ["x"])
    cache.put("b", ["y"])
    cache.forget("b")
    assert cache.get("b", old) is None and cache.get("a", old) == ["x"]
    clock.now += flow_port.CACHE_TTL_S + 1
    cache.put("c", ["z"])
    assert set(cache._held) == {"c"}


def test_a_session_seed_and_a_bad_window(dispatcher, tmp_path):
    ctx = _ctx(tmp_path, "flow.read")
    run = _call(dispatcher, ctx, {"seed": "session", "id": fx.F, "start": fx.BASE, "end": fx.BASE + 600})["run"]
    assert {l["id"] for l in run["lanes"] if l["kind"] == "session"} == {f"s:{fx.F}", f"s:{fx.B}"}
    assert _call(dispatcher, ctx, {"id": "395", "start": "soon"}).code == "invalid_params"
    assert _call(dispatcher, ctx, {"id": "395", "end": -1}).code == "invalid_params"
    assert _call(dispatcher, ctx, {"id": "395", "start": True}).code == "invalid_params"

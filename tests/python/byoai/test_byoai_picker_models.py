
from __future__ import annotations

import asyncio

import pytest

from src.core.byoai import model_catalog
from src.core.byoai.calllog import CallLog, CallRecord
from src.core.byoai.contracts import Connection, ModelInfo, ProviderHTTPError
from src.core.byoai.presets import get_preset
from src.core.byoai.wire._shared import infer_model


def test_openrouter_entry_carries_price_context_and_modalities() -> None:
    entry = {"id": "a/b", "name": "A B", "context_length": 200000,
             "pricing": {"prompt": "0.000003", "completion": "0.000015"},
             "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
             "supported_parameters": ["tools"]}
    m = infer_model("a/b", entry)
    assert (m.context_length, m.price_in, m.price_out) == (200000, 3.0, 15.0)
    assert m.inputs == ("text", "image") and m.outputs == ("text",)
    assert "tools" in m.flags and "vision" in m.flags
    assert infer_model("r/auto", {"pricing": {"prompt": "-1", "completion": "-1"}}).price_in is None


def test_router_entry_takes_the_cheapest_provider() -> None:
    entry = {"id": "Q/x", "providers": [{"provider": "p1", "context_length": 1000, "pricing": {"input": 0.5, "output": 2}},
                                         {"provider": "p2", "context_length": 5000, "pricing": {"input": 0.4, "output": 3}, "supports_tools": True}]}
    m = infer_model("Q/x", entry)
    assert (m.context_length, m.price_in, m.price_out) == (5000, 0.4, 3.0) and "tools" in m.flags


def test_featured_ranks_prefix_picks_the_newest_and_exact_wins() -> None:
    preset = get_preset("anthropic")
    ids = ["claude-sonnet-4-5-20250929", "claude-sonnet-4-20250514", "claude-opus-4-1", "claude-haiku-4-5"]
    ranks = model_catalog.featured_ranks(preset, [ModelInfo(i) for i in ids])
    assert ranks == {"claude-opus-4-1": 0, "claude-sonnet-4-5-20250929": 1, "claude-haiku-4-5": 2}


def test_provider_popularity_ranks_and_fails_soft() -> None:
    preset = get_preset("openrouter")
    conn = Connection("or-1", "openrouter")
    models = [ModelInfo("a/one"), ModelInfo("b/two"), ModelInfo("c/three")]

    class Resp:
        def json(self) -> dict:
            return {"data": [{"id": "c/three"}, {"id": "gone/x"}, {"id": "a/one"}]}

    async def ok(_protocol, _call):
        return Resp()

    async def bad(_protocol, _call):
        raise ProviderHTTPError(500, "down")

    ranked = asyncio.run(model_catalog._rank_by_provider(conn, preset, "openai_chat", models, ok))
    assert {m.id: m.meta.get("popular_rank") for m in ranked} == {"a/one": 1, "b/two": None, "c/three": 0}
    same = asyncio.run(model_catalog._rank_by_provider(conn, preset, "openai_chat", models, bad))
    assert same == models


def test_recent_models_newest_first_successful_only(tmp_path) -> None:
    log = CallLog(tmp_path)
    for model, ok in (("m1", True), ("m2", True), ("m3", False), ("m1", True)):
        log.record(CallRecord("chat", ok, connection_id="c1", model=model))
    log.record(CallRecord("chat", True, connection_id="other", model="zz"))
    assert [r["model"] for r in log.recent_models("c1")] == ["m1", "m2"]


def test_an_old_cached_list_reads_as_a_miss(tmp_path) -> None:
    log = CallLog(tmp_path)
    log.put_models("c1", [ModelInfo("m", context_length=10)])
    assert log.get_models("c1")[1][0].context_length == 10
    import json, sqlite3
    conn = sqlite3.connect(log.db_path)
    conn.execute("UPDATE models SET payload=?", (json.dumps([{"id": "m", "capabilities": [], "flags": [], "label": "", "meta": {}}]),))
    conn.commit(); conn.close()
    assert log.get_models("c1") is None


def test_image_output_models_get_the_image_capability() -> None:
    only = {"architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}}
    both = {"architecture": {"input_modalities": ["text", "image"], "output_modalities": ["image", "text"]}}
    assert infer_model("openai/gpt-image-2", only).capabilities == ("image",)
    assert infer_model("openai/gpt-5.4-image-2", both).capabilities == ("chat", "image")
    assert infer_model("a/b", {"architecture": {"output_modalities": ["text"]}}).capabilities == ("chat",)

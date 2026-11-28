
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi import HTTPException

from src.core.mcp import stats_tools, tool_switches, tools
from tests.python.mcp.test_mcp_route_adapters import PANE, READ_ONLY, View, world  # noqa: F401

SPECS = stats_tools.SPECS
NAMES = [s.name for s in SPECS]
FROM, TO = "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"
UID = "00000000-0000-4000-8000-000000000001"
SECRET = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def _call(name: str, args: dict, caller=PANE) -> dict:
    return asyncio.run(tools.call_tool(View(), caller, name, args))


def _record(monkeypatch, route: str, answer=None) -> list:
    seen: list = []
    module, name = route.split(":")

    async def recorder(*args, **kwargs):
        seen.append((args, kwargs))
        return answer if answer is not None else {"ok": True}

    monkeypatch.setattr(f"{module}.{name}", recorder)
    return seen


def test_there_are_seventeen_read_tools_and_a_read_token_runs_each(world):
    assert len(SPECS) == 17 and all(s.gate == "read" and s.redact for s in SPECS)
    listed = {d["name"] for d in tools.tool_definitions(READ_ONLY)}
    assert set(NAMES) <= listed and not set(NAMES) & tools.WRITE_TOOLS
    for spec in SPECS:
        assert not _call(spec.name, dict(spec.example), READ_ONLY).get("isError"), spec.name


def test_contributions_passes_every_query_parameter_as_a_plain_value(monkeypatch, world):
    seen = _record(monkeypatch, "src.api.stats_routes:get_contributions")
    _call("stats_contributions_list", {"metric": "total_tokens", "from": FROM, "to": TO, "provider": "claude", "limit": 7})
    (_, kw), = seen
    assert kw["from_"] == datetime(2026, 11, 1, tzinfo=timezone.utc) and kw["to"].tzinfo is not None
    assert (kw["metric"], kw["timezone_name"], kw["resolution"], kw["limit"], kw["cursor"]) == ("total_tokens", "UTC", "auto", 7, 0)
    assert kw["provider"] == "claude" and kw["project"] is None and kw["conversation_id"] is None


def test_dimensions_range_is_optional_and_filters_are_explicit(monkeypatch, world):
    seen = _record(monkeypatch, "src.api.stats_routes:get_dimensions")
    _call("stats_dimensions_list", {"dimension": "model"})
    (_, kw), = seen
    assert kw["from_"] is None and kw["to"] is None and kw["account_id"] is None and kw["window"] is None
    assert (kw["limit"], kw["cursor"], kw["dimension"]) == (stats_tools.DEFAULT_CONTRIBUTION_ROWS, 0, "model")


def test_annotations_event_log_and_conversations_pass_defaults(monkeypatch, world):
    ann = _record(monkeypatch, "src.api.stats_routes:get_events")
    log = _record(monkeypatch, "src.api.stats_event_routes:get_event_log")
    conv = _record(monkeypatch, "src.api.stats_insight_routes:get_conversations")
    base = {"from": FROM, "to": TO}
    _call("stats_annotations_list", base)
    _call("stats_events_list", {**base, "kind": "error"})
    _call("stats_conversations_list", base)
    assert ann[0][1]["limit"] == stats_tools.DEFAULT_EVENT_ROWS and ann[0][1]["cursor"] == 0 and ann[0][1]["host"] is None
    assert log[0][1]["kind"] == "error" and log[0][1]["limit"] == stats_tools.DEFAULT_EVENT_ROWS
    assert conv[0][1]["limit"] == stats_tools.MAX_CONVERSATIONS and conv[0][1]["provider"] is None


def test_impact_chart_and_tripwire_take_uuids_and_impact_defaults(monkeypatch, world):
    impact = _record(monkeypatch, "src.api.stats_insight_routes:get_impact")
    chart = _record(monkeypatch, "src.api.stats_routes:get_chart")
    wire = _record(monkeypatch, "src.api.stats_tripwire_routes:get_tripwire")
    _call("stats_impact_get", {"annotation_id": UID})
    _call("stats_chart_get", {"chart_id": UID})
    _call("stats_tripwire_get", {"tripwire_id": UID})
    assert impact[0][1] == {"annotation_id": UUID(UID), "metric": "estimated_cost_nano_usd", "days": 7}
    assert chart[0][0][1] == UUID(UID) and wire[0][0][1] == UUID(UID)


def test_query_and_batch_build_the_routes_own_body_models(monkeypatch, world):
    one = _record(monkeypatch, "src.api.stats_routes:post_query")
    many = _record(monkeypatch, "src.api.stats_routes:post_query_batch")
    _call("stats_query_run", {"metric": "total_tokens", "from": FROM, "to": TO, "operation": "summary"})
    _call("stats_query_batch_run", {"items": [{"metric": "total_tokens", "rolling": "24h"}]})
    body = one[0][0][1]
    assert body.metric == "total_tokens" and body.operation == "summary" and body.from_.year == 2026
    assert many[0][0][1].items == [{"metric": "total_tokens", "rolling": "24h"}]


@pytest.mark.parametrize("name,args", [
    ("stats_contributions_list", {"metric": "m", "from": FROM, "to": TO, "limit": 0}),
    ("stats_contributions_list", {"metric": "m", "from": FROM, "to": TO, "limit": 201}),
    ("stats_contributions_list", {"metric": "m", "from": FROM, "to": TO, "cursor": -1}),
    ("stats_contributions_list", {"metric": "m", "from": "yesterday", "to": TO}),
    ("stats_contributions_list", {"metric": "m", "from": FROM, "to": TO, "project": 5}),
    ("stats_dimensions_list", {"dimension": "nope"}),
    ("stats_annotations_list", {"from": FROM, "to": TO, "limit": True}),
    ("stats_conversations_list", {"from": FROM, "to": TO, "limit": 501}),
    ("stats_impact_get", {"annotation_id": "not-a-uuid"}),
    ("stats_impact_get", {"annotation_id": UID, "metric": "nope"}),
    ("stats_impact_get", {"annotation_id": UID, "days": 31}),
    ("stats_chart_get", {"chart_id": "x"}),
    ("stats_tripwire_get", {"tripwire_id": "x"}),
    ("stats_events_list", {"from": FROM}),
    ("stats_query_run", {"rolling": "24h"}),
    ("stats_catalog_get", {"extra": 1}),
])
def test_a_bad_argument_is_refused_before_any_route_runs(world, name, args):
    answer = _call(name, args)
    assert answer["isError"] is True and world == []


def test_a_bad_query_body_is_the_tools_error_not_a_crash(world):
    answer = _call("stats_query_run", {"metric": "total_tokens", "rolling": "24h", "bogus": 1})
    assert answer["isError"] is True and world == []
    answer = _call("stats_query_run", {"metric": "total_tokens", "rolling": "24h", "top_n": 99})
    assert answer["isError"] is True and world == []


def test_a_route_refusal_reads_as_a_tool_error(monkeypatch, world):
    async def refuse(*args, **kwargs):
        raise HTTPException(409, detail={"code": "stats_off", "message": "stats off"})

    monkeypatch.setattr("src.api.stats_routes.get_coverage", refuse)
    answer = _call("stats_coverage_get", {})
    assert answer["isError"] is True and "409" in json.dumps(answer) and "stats off" in json.dumps(answer)


@pytest.mark.parametrize("spec", SPECS, ids=NAMES)
def test_every_answer_is_redacted_and_keeps_its_keys(monkeypatch, world, spec):
    async def route(*args, **kwargs):
        return {"total_tokens": 12, "title": f"use {SECRET}"}

    module, name = spec.route.split(":")
    monkeypatch.setattr(f"{module}.{name}", route)
    answer = _call(spec.name, dict(spec.example))
    assert not answer.get("isError"), answer
    text = json.dumps(answer)
    assert SECRET not in text and "total_tokens" in text


def test_the_drill_downs_ship_switched_off_and_the_core_five_stay_on() -> None:
    off = {n for n in NAMES if n in tool_switches.RARELY_USED}
    on = set(NAMES) - off
    assert on == {"stats_catalog_get", "stats_settings_get", "stats_live_get", "stats_query_run", "stats_query_batch_run"}
    assert tool_switches.RARELY_USED <= set(tools.tool_names())

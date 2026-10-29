
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List, Optional

import pytest

from tests.test_session_token_usage import UUID, _assistant, _write_lines

# ruff: noqa: E402
from src.core.session_token_usage import claude_reader
from src.core.session_token_usage.cache import IncrementalCache, TranscriptTotals
from src.core.session_token_usage.model_table import (
    COST_TIER_THRESHOLDS,
    MODEL_TABLE,
    cost_tier_for_model,
    display_name_for_model,
    estimate_cost_usd,
    facts_for_model,
    window_for_model,
)




def test_cache_reads_only_the_appended_tail(tmp_path, monkeypatch):
    path = tmp_path / "t.jsonl"
    first = json.dumps(
        _assistant("msg_1", "claude-opus-5", inp=10, cache_creation=0,
                   cache_read=0, out=5)
    )
    _write_lines(path, [first])

    cache = IncrementalCache()
    starts: List[int] = []
    real_scan = claude_reader.scan_lines

    def _spy(handle, totals):
        starts.append(handle.tell())
        return real_scan(handle, totals)

    monkeypatch.setattr(claude_reader, "scan_lines", _spy)

    first_totals = claude_reader.read_transcript_totals(path, cache=cache)
    assert first_totals is not None and first_totals.input_tokens == 10
    assert starts == [0]

    second = json.dumps(
        _assistant("msg_2", "claude-opus-5", inp=7, cache_creation=0,
                   cache_read=0, out=3)
    )
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(second + "\n")

    totals = claude_reader.read_transcript_totals(path, cache=cache)

    assert totals is not None
    assert totals.input_tokens == 17
    assert totals.output_tokens == 8
    assert starts[1] == len(first) + 1


def test_cache_rescans_from_zero_when_the_file_shrinks(tmp_path):
    path = tmp_path / "t.jsonl"
    _write_lines(path, [
        json.dumps(_assistant("msg_1", "claude-opus-5", inp=10,
                              cache_creation=0, cache_read=0, out=5)),
        json.dumps(_assistant("msg_2", "claude-opus-5", inp=10,
                              cache_creation=0, cache_read=0, out=5)),
    ])
    cache = IncrementalCache()
    assert claude_reader.read_transcript_totals(path, cache=cache).input_tokens == 20

    _write_lines(path, [
        json.dumps(_assistant("msg_9", "claude-opus-5", inp=3,
                              cache_creation=0, cache_read=0, out=1)),
    ])
    totals = claude_reader.read_transcript_totals(path, cache=cache)

    assert totals.input_tokens == 3
    assert totals.output_tokens == 1


def test_cache_rescans_when_the_head_changed_at_the_same_size(tmp_path):
    path = tmp_path / "t.jsonl"
    first = json.dumps(_assistant("msg_1", "claude-opus-5", inp=10,
                                  cache_creation=0, cache_read=0, out=5))
    _write_lines(path, [first])
    cache = IncrementalCache()
    assert claude_reader.read_transcript_totals(path, cache=cache).input_tokens == 10

    replacement = json.dumps(_assistant("msg_2", "claude-opus-5", inp=10,
                                        cache_creation=0, cache_read=0, out=5))
    assert len(replacement) == len(first)
    _write_lines(path, [replacement])

    totals = claude_reader.read_transcript_totals(path, cache=cache)
    assert totals.input_tokens == 10


def test_cache_ignores_a_half_written_final_line(tmp_path):
    path = tmp_path / "t.jsonl"
    complete = json.dumps(_assistant("msg_1", "claude-opus-5", inp=10,
                                     cache_creation=0, cache_read=0, out=5))
    partial = json.dumps(_assistant("msg_2", "claude-opus-5", inp=99,
                                    cache_creation=0, cache_read=0, out=99))
    path.write_text(complete + "\n" + partial[:20], encoding="utf-8")

    cache = IncrementalCache()
    assert claude_reader.read_transcript_totals(path, cache=cache).input_tokens == 10

    path.write_text(complete + "\n" + partial + "\n", encoding="utf-8")
    totals = claude_reader.read_transcript_totals(path, cache=cache)
    assert totals.input_tokens == 109




def test_cost_arithmetic_on_a_known_model():
    assert estimate_cost_usd(
        "claude-opus-5",
        input_tokens=1_000_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=0,
    ) == 5.0
    assert estimate_cost_usd(
        "claude-opus-5",
        input_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
        output_tokens=1_000_000,
    ) == 36.75


def test_cost_is_none_for_a_model_the_table_does_not_carry():
    assert estimate_cost_usd(
        "unknown-model",
        input_tokens=1_000_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=1_000_000,
    ) is None
    assert window_for_model("unknown-model") is None
    assert facts_for_model(None) is None


def test_longest_prefix_wins_so_a_point_release_is_not_mispriced():
    assert facts_for_model("claude-fable-5-1").prices.cache_read == 0.25
    assert facts_for_model("claude-fable-5").prices.cache_read == 1.0
    assert facts_for_model("claude-opus-5-20260401").window_tokens == 1_000_000


def test_opus_5_5_is_priced_as_itself_not_as_opus_5():
    facts = facts_for_model("claude-opus-5-5")
    assert facts.display_name == "Opus 5.5"
    assert facts.window_tokens == 1_000_000
    assert (facts.prices.input, facts.prices.cache_write,
            facts.prices.cache_read, facts.prices.output) == (4.0, 5.0, 0.2, 20.0)
    assert facts_for_model("claude-opus-5").prices.output == 25.0
    assert cost_tier_for_model("claude-opus-5-5") == 4


def test_cost_tier_is_derived_from_the_output_price_and_uses_all_five_steps():
    assert cost_tier_for_model("gpt-5-nano") == 1
    assert cost_tier_for_model("gpt-5-mini") == 2
    assert cost_tier_for_model("claude-haiku-4-5") == 2
    assert cost_tier_for_model("claude-sonnet-5") == 3
    assert cost_tier_for_model("claude-sonnet-4-6") == 3
    assert cost_tier_for_model("claude-opus-5") == 4
    assert cost_tier_for_model("claude-fable-5-1") == 5
    assert cost_tier_for_model("claude-opus-5-20260401") == 4
    tiers = {cost_tier_for_model(prefix) for prefix in MODEL_TABLE}
    assert tiers == {1, 2, 3, 4, 5}
    assert len(COST_TIER_THRESHOLDS) == 4


def test_an_unknown_model_gets_no_name_and_no_tier():
    assert display_name_for_model("unknown-model") is None
    assert cost_tier_for_model("unknown-model") is None
    assert display_name_for_model(None) is None
    assert cost_tier_for_model(None) is None
    assert display_name_for_model("claude-opus-5") == "Opus 5"
    assert display_name_for_model("claude-opus-5-20260401") == "Opus 5"
    missing = [p for p, f in MODEL_TABLE.items() if not f.display_name]
    assert missing == []


def test_totals_never_fabricate_a_negative_or_a_float():
    totals = TranscriptTotals().plus_usage(
        {"input_tokens": -5, "output_tokens": "x", "cache_read_input_tokens": None},
        model=None,
        message_id="m",
    )
    assert totals.input_tokens == 0
    assert totals.output_tokens == 0
    assert totals.cache_read_input_tokens == 0




class _StubSession:

    def __init__(self, working_dir: Optional[str]) -> None:
        self.working_dir = working_dir


class _StubInfo:

    def __init__(self, family: Optional[str], tmux_name: Optional[str],
                 working_dir: Optional[str]) -> None:
        self.agent_family = family
        self.tmux_session = tmux_name
        self.session = _StubSession(working_dir)


class _StubManager:

    def __init__(self, rows: dict, uuid: Optional[str]) -> None:
        self._rows = rows
        self._uuid = uuid

    async def get_session_info(self, session_id: Optional[str] = None):
        return self._rows.get(session_id)

    def _claude_uuid_for_tmux_name(self, tmux_name: str) -> Optional[str]:
        return self._uuid

    def _tmux_socket_name(self) -> str:
        from tests.socket_guard import TEST_SOCKET_NAME

        return TEST_SOCKET_NAME


def _client(rows: dict, uuid: Optional[str]):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.session_token_usage_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = _StubManager(rows, uuid)
    return TestClient(app)


def test_route_returns_the_measured_usage_for_a_created_session(tmp_path,
                                                                monkeypatch):
    corpus = tmp_path / "projects"
    (corpus / "-tmp-project").mkdir(parents=True)
    _write_lines(
        corpus / "-tmp-project" / f"{UUID}.jsonl",
        [json.dumps(_assistant("msg_1", "claude-opus-5", inp=10,
                               cache_creation=20, cache_read=30, out=40))],
    )
    import src.api.session_token_usage_routes as routes_mod

    real = routes_mod.read_session_token_usage
    monkeypatch.setattr(
        routes_mod,
        "read_session_token_usage",
        lambda subject: real(subject, projects_dir=corpus),
    )

    rows = {"ses_1": _StubInfo("claude", "cloude_a", None)}
    response = _client(rows, UUID).get("/api/v1/sessions/ses_1/token-usage")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ok"
    assert body["family"] == "claude"
    assert body["model"] == "claude-opus-5"
    assert body["input_tokens"] == 10
    assert body["total_tokens"] == 100
    assert body["as_of"].endswith("+00:00")
    assert "source_path" not in body
    assert not any("/" in str(v) for k, v in body.items() if k == "detail" and v)


def test_route_resolves_an_adopted_session_id(tmp_path, monkeypatch):
    import src.api.session_token_usage_routes as routes_mod

    real = routes_mod.read_session_token_usage
    monkeypatch.setattr(
        routes_mod,
        "read_session_token_usage",
        lambda subject: real(subject, projects_dir=tmp_path / "empty"),
    )

    rows = {"adopted:cloude_x": _StubInfo("claude", "cloude_x", None)}
    response = _client(rows, UUID).get(
        "/api/v1/sessions/adopted:cloude_x/token-usage"
    )

    assert response.status_code == 200
    assert response.json()["state"] == "unchecked"


def test_route_404s_on_an_unknown_session_id():
    response = _client({}, UUID).get("/api/v1/sessions/ses_nope/token-usage")
    assert response.status_code == 404


def test_route_is_registered_on_the_api_router(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import src.api.session_token_usage_routes as routes_mod
    from src.api.auth import require_auth
    from src.api.routes import router
    from src.models.session_token_usage import SessionTokenUsage

    canned = SessionTokenUsage(
        state="ok", family="claude", model="claude-opus-5", input_tokens=1,
        output_tokens=2, cache_read_input_tokens=3,
        cache_creation_input_tokens=4, total_tokens=10,
        as_of="2026-09-19T00:00:00+00:00",
    )
    monkeypatch.setattr(routes_mod, "read_session_token_usage", lambda s: canned)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = _StubManager(
        {"ses_1": _StubInfo("claude", "cloude_a", None)}, UUID
    )
    client = TestClient(app)

    response = client.get("/api/v1/sessions/ses_1/token-usage")
    assert response.status_code == 200
    assert response.json()["total_tokens"] == 10

    missing = client.get("/api/v1/sessions/ses_1/not-a-route")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Not Found"

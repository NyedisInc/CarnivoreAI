
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import search_index_routes
from src.core import cross_session_search
from tests.python.deepsearch.helpers import build_world, drain, go_ready, mount, rec, scan, teardown
from tests.python.transcript_source.helpers import CONV

PROMPT_ONLY = "wombatprompt"
REPLY_ONLY = "quokkareply"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    with open(built["main"], "ab") as handle:
        handle.write(rec(5, f"please check the {PROMPT_ONLY} setting"))
        handle.write(rec(6, f"done, the answer is {REPLY_ONLY}", "assistant"))
    app = mount(built, monkeypatch)
    app.include_router(search_index_routes.router, prefix="/api/v1")
    monkeypatch.setattr(search_index_routes, "_state_dir", lambda: built["state"])
    scan(built)
    drain(built)
    go_ready(built)
    built["app"] = app
    yield built
    teardown()


def _counts(client: TestClient, word: str) -> tuple:
    prompts = client.get("/api/v1/pipeline/prompts/search", params={"q": word}).json()
    database = client.get("/api/v1/deepsearch/search", params={"q": word}).json()
    return prompts["total_matches"], database["total_matches"]


def test_prompts_finds_only_what_the_user_typed_database_finds_replies_too(world):
    with TestClient(world["app"]) as client:
        assert _counts(client, REPLY_ONLY) == (0, 1)
        assert _counts(client, PROMPT_ONLY) == (1, 1)
        body = client.get("/api/v1/pipeline/prompts/search", params={"q": PROMPT_ONLY}).json()
    assert body["kinds"] == ["user"] and [g["conversation_id"] for g in body["groups"]] == [CONV]
    assert {h["kind"] for g in body["groups"] for h in g["hits"]} == {"user"}
    assert f"\x02{PROMPT_ONLY}\x03" in body["groups"][0]["hits"][0]["snippet"]
    assert body["ingest"]["state"] == "running"


def test_grep_reads_the_scrollback_so_it_sees_the_reply_prompts_cannot(world):
    scrollback = f"> please check the {PROMPT_ONLY} setting\ndone, the answer is {REPLY_ONLY}\n"
    assert cross_session_search.find_matches(scrollback, REPLY_ONLY, 10)[0] == 1
    assert cross_session_search.find_matches(scrollback, PROMPT_ONLY, 10)[0] == 1


def test_prompts_route_validates_and_still_answers_with_a_stored_off_switch(world):
    with TestClient(world["app"]) as client:
        assert client.get("/api/v1/pipeline/prompts/search", params={"q": "   "}).status_code == 422
        off = client.get("/api/v1/pipeline/prompts/search", params={"q": PROMPT_ONLY}).json()
    assert off["total_matches"] == 1 and off["ingest"]["state"] == "running" and off["ingest"]["reason"] is None

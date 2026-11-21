
from __future__ import annotations

import json
import random
import string
import uuid
from typing import Any, Dict, List

import pytest

from src.plugins.reviewboard.public import responses
from src.plugins.reviewboard.public.write import WRITER
from src.plugins.sdk import ports
from tests.python.cplugs.reviewboard.public.read_harness import edge, get, mint_token

SLUG = "20261013-bottom-bar"
FAKE_KEY = "ghp_" + "".join(random.Random(2697).choices(string.ascii_letters + string.digits, k=36))


class SpyBoardPort:

    def __init__(self) -> None:
        self.calls: List[str] = []

    def __getattr__(self, name: str) -> Any:
        self.calls.append(name)

        async def call(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            return {"posted": True, "told": True, "message_id": 1}
        return call


@pytest.fixture
def spy() -> Any:
    port = SpyBoardPort()
    previous = ports.get("huddle.board")
    ports.register("huddle.board", port)
    yield port
    ports.register("huddle.board", previous) if previous is not None else ports.unregister("huddle.board")


def post(path: str, token: str, body: Dict[str, Any], **kw: Any) -> Any:
    kw.setdefault("extra", (("Carnivore-Visitor", "0000" + "k" * 18),))
    return get(edge(), path, token, method="POST", body=json.dumps(body).encode(), **kw)


def pid() -> str:
    return uuid.uuid4().hex


def rows(read_env: Any) -> List[responses.Response]:
    return responses.list_board(responses.storage_for(read_env.host.storage("reviewboard").path), SLUG)


ANSWERS = [{"prompt": "layout", "options": ["b"]}, {"prompt": "padding", "checked": True}, {"prompt": "extra", "text": "a count badge", "note": "small"}]


def test_a_comment_lands_in_the_plugins_own_store_and_nowhere_else(read_env, store, spy) -> None:
    token = mint_token(store)
    got = post("/api/comments", token, {"client_post_id": pid(), "name": "sam", "text": "too close to the edge", "anchor": "send"})
    assert (got.status, got.json()) == (201, {"state": "received", "duplicate": False})
    stored = rows(read_env)
    assert [(r.kind, r.name, r.revision) for r in stored] == [("comment", "sam", "r1")]
    assert stored[0].body == {"text": "too close to the edge", "anchor": "send"} and all(r.forwarded_at is None for r in stored)
    assert spy.calls == []
    folder = responses.storage_for(read_env.host.storage("reviewboard").path).db_path
    assert folder.stat().st_mode & 0o777 == 0o600


def test_a_repeated_client_post_id_lands_once(read_env, store, spy) -> None:
    token, same = mint_token(store), pid()
    first = post("/api/comments", token, {"client_post_id": same, "text": "once"})
    again = post("/api/comments", token, {"client_post_id": same, "text": "once"})
    assert (first.status, again.status, again.json()["duplicate"]) == (201, 200, True)
    assert len(rows(read_env)) == 1


@pytest.mark.parametrize("body", [
    {"answers": [{"prompt": "layout", "options": ["z"]}]},
    {"answers": [{"prompt": "nope", "checked": True}]},
    {"answers": [{"prompt": "padding", "text": "yes"}]},
    {"payload": {"layer": "questions", "v": 1, "values": {}}},
])
def test_answers_that_do_not_fit_the_revision_are_rejected_and_not_stored(read_env, store, spy, body) -> None:
    got = post("/api/draft", mint_token(store), {"revision": "r1", **body})
    assert (got.status, got.json()) == (422, {"state": "rejected"}) and rows(read_env) == []


def test_the_answers_route_is_gone(read_env, store, spy) -> None:
    got = post("/api/answers", mint_token(store), {"client_post_id": pid(), "answers": ANSWERS})
    assert got.status == 404 and rows(read_env) == []


def test_a_comment_on_an_undeclared_anchor_or_item_is_rejected(read_env, store, spy) -> None:
    token = mint_token(store)
    for target in ({"anchor": "nowhere"}, {"item": "nothing"}):
        got = post("/api/comments", token, {"client_post_id": pid(), "text": "hi", **target})
        assert got.json() == {"state": "rejected"}
    assert rows(read_env) == []


@pytest.mark.parametrize("body", [
    {"text": "hi", "extra": 1},
    {"text": "a\x1b[2Jb"},
    {"text": "line\u2028break"},
    {"text": "ok", "name": "two\nlines"},
    {"text": "x" * 4001},
    {"text": "ok", "anchor": "send", "item": "x"},
    {"text": "ok", "name": "n" * 61},
])
def test_a_malformed_comment_is_refused(read_env, store, spy, body) -> None:
    got = post("/api/comments", mint_token(store), {"client_post_id": pid(), **body})
    assert (got.status, got.json()) == (400, {"state": "malformed"}) and rows(read_env) == []


def test_a_credential_is_refused_and_nothing_is_stored_or_echoed(read_env, store, spy) -> None:
    token = mint_token(store)
    for path, body in (("/api/comments", {"text": f"use {FAKE_KEY}"}), ("/api/draft", {"revision": "r1", "answers": [{"prompt": "extra", "text": FAKE_KEY}]}),
                       ("/api/comments", {"text": "fine", "name": FAKE_KEY[:40]})):
        got = post(path, token, body if path == "/api/draft" else {"client_post_id": pid(), **body})
        assert got.status == 422 and got.json()["state"] == "has_secret" and got.json()["detectors"], body
        assert FAKE_KEY[:20].encode() not in got.body
    assert rows(read_env) == [] and spy.calls == []


def test_the_post_rate_limit_answers_429(read_env, store, spy) -> None:
    WRITER.bind(WRITER.deps, posts_per_min=2)
    token = mint_token(store)
    statuses = [post("/api/comments", token, {"client_post_id": pid(), "text": "n"}).status for _ in range(3)]
    assert statuses == [201, 201, 429]
    other = post("/api/comments", token, {"client_post_id": pid(), "text": "n"}, forwarded="198.51.100.2")
    assert other.status == 201


def test_a_spent_board_cap_is_full_and_stores_nothing_more(read_env, store, spy, monkeypatch) -> None:
    monkeypatch.setattr(responses, "MAX_PER_BOARD", 1)
    token = mint_token(store)
    assert post("/api/comments", token, {"client_post_id": pid(), "text": "a"}).status == 201
    full = post("/api/comments", token, {"client_post_id": pid(), "text": "b"})
    assert (full.status, full.json()) == (507, {"state": "full"}) and len(rows(read_env)) == 1


def test_a_post_needs_a_live_capability(read_env, store, spy) -> None:
    for token in (None, "garbage"):
        got = get(edge(), "/api/comments", token, method="POST", body=b'{"client_post_id":"aaaaaaaa","text":"x"}')
        assert got.json() == {"state": "invalid"}
    assert rows(read_env) == []


def test_owner_routes_are_not_on_the_public_listener(read_env, store) -> None:
    token = mint_token(store)
    for path in ("/api/v1/cplugs/reviewboard/public/visitors/forward", "/api/v1/cplugs/reviewboard/public/visitors", "/visitors/forward", "/api/forward"):
        assert post(path, token, {"board": SLUG}).status == 404, path
        assert get(edge(), path, token).status == 404, path


def test_ipv6_posters_share_one_post_budget_per_64(read_env, store, spy) -> None:
    WRITER.bind(WRITER.deps, posts_per_min=2)
    token = mint_token(store)
    send = [post("/api/comments", token, {"client_post_id": pid(), "text": "n"}, forwarded=f"2001:db8:1:2::{n}").status for n in (1, 2, 3)]
    assert send == [201, 201, 429]
    assert post("/api/comments", token, {"client_post_id": pid(), "text": "n"}, forwarded="2001:db8:1:3::1").status == 201

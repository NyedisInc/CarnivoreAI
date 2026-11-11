
from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, List, Optional

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.reviewboard.public import drafts, links, minting, responses, theme
from src.cplugs.reviewboard.public.read import READER
from src.cplugs.reviewboard.public.write import WRITER
from tests.python.cplugs.reviewboard.public.read_harness import add_revision, call, edge, get, mint_token

SLUG = "20261013-bottom-bar"
VISITORS = "/api/v1/cplugs/reviewboard/public/visitors"
LINKS = "/api/v1/cplugs/reviewboard/public/links"
ANSWERS = [{"prompt": "layout", "options": ["b"]}, {"prompt": "padding", "checked": True}]


def key(n: int = 0) -> str:
    return f"{n:04d}" + "k" * 18


def post(path: str, token: str, body: Dict[str, Any], visitor: Optional[str] = None) -> Any:
    extra = (("Carnivore-Visitor", visitor),) if visitor else ()
    return get(edge(), path, token, method="POST", body=json.dumps(body).encode(), extra=extra)


def board(token: str, visitor: Optional[str] = None) -> Any:
    return get(edge(), "/api/board", token, extra=(("Carnivore-Visitor", visitor),) if visitor else ())


def mint(store: Any, **kw: Any) -> str:
    mode = kw.pop("mode", "pinned")
    return asyncio.run(minting.mint_link(SimpleNamespace(storage=store), SLUG, "1d", mode, **kw))["token"]


def response_store(read_env: Any) -> Any:
    return responses.storage_for(read_env.host.storage("reviewboard").path)


@pytest.fixture
def owner(read_env: Any) -> Iterator[TestClient]:
    read_env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(read_env.app) as client:
        yield client
    read_env.app.dependency_overrides.clear()



def test_a_read_only_link_refuses_every_visitor_write_server_side(read_env, store) -> None:
    token = mint(store, access="read")
    assert board(token).json()["access"] == "read"
    sends = [("/api/comments", {"client_post_id": uuid.uuid4().hex, "text": "hello"}),
             ("/api/draft", {"revision": "r1", "answers": ANSWERS})]
    for path, body in sends:
        got = post(path, token, body, key())
        assert (got.status, got.json()) == (403, {"state": "read_only"}), path
    assert responses.list_board(response_store(read_env), SLUG) == [] and drafts.list_board(response_store(read_env), SLUG) == []


def test_a_new_link_answers_by_default_and_the_owner_route_takes_the_access(read_env, owner) -> None:
    made = owner.post(LINKS, json={"board": SLUG, "ttl": "1d"}).json()
    assert made["link"]["access"] == "answer"
    made = owner.post(LINKS, json={"board": SLUG, "ttl": "1d", "access": "read"}).json()
    assert made["link"]["access"] == "read" and board(made["token"]).json()["access"] == "read"
    assert owner.post(LINKS, json={"board": SLUG, "ttl": "1d", "access": "write"}).status_code == 422


def test_an_expired_or_revoked_link_refuses_a_draft(read_env, store) -> None:
    token = mint(store)
    links.revoke_board(store, SLUG)
    got = post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key())
    assert (got.status, got.json()) == (404, {"state": "ended"})
    assert drafts.list_board(response_store(read_env), SLUG) == []



def test_the_owners_theme_rides_the_link_to_the_visitor_page(read_env, owner) -> None:
    palette = {"--oc-orange": "rgb(255, 128, 0)", "--oc-ground-page": "#101010"}
    token = owner.post(LINKS, json={"board": SLUG, "ttl": "1d", "theme": palette}).json()["token"]
    assert board(token).json()["theme"] == palette


@pytest.mark.parametrize("bad", [{"--oc-x": "red; background: url(https://x.test)"}, {"--oc-x": "</style>"}, {"color": "red"},
                                 {"--oc-x": "url(https://x.test/a.png)"}, {"--oc-x": "a\u0007b"}, {"--oc-x": "expression(alert(1))"}])
def test_a_theme_entry_that_could_break_out_is_left_out(read_env, owner, bad) -> None:
    token = owner.post(LINKS, json={"board": SLUG, "ttl": "1d", "theme": {**bad, "--oc-orange": "#f80"}}).json()["token"]
    assert board(token).json()["theme"] == {"--oc-orange": "#f80"}


def test_a_theme_that_is_not_a_map_of_strings_is_refused(read_env, owner) -> None:
    assert owner.post(LINKS, json={"board": SLUG, "ttl": "1d", "theme": ["--oc-x"]}).status_code == 422
    assert links.list_links(read_env.host.storage("reviewboard"), SLUG) == []


def test_a_stored_theme_is_checked_again_on_the_way_out() -> None:
    assert theme.loads('{"--oc-x": "red}"}') is None and theme.loads("not json") is None and theme.loads("[1]") is None
    assert theme.loads('{"--oc-x": "url(data:image/gif,AA)"}') == {"--oc-x": "url(data:image/gif,AA)"}



def test_a_draft_autosaves_as_that_visitors_own_and_comes_back_after_a_reload(read_env, store) -> None:
    token = mint_token(store)
    got = post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(1))
    assert (got.status, got.json()) == (200, {"state": "saved", "changed": True})
    assert post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(1)).json()["changed"] is False
    assert board(token, key(1)).json()["draft"] == {"body": {"answers": ANSWERS}}
    assert board(token, key(2)).json()["draft"] is None and board(token).json()["draft"] is None


def test_visitors_are_numbered_per_board_in_first_seen_order_and_the_wire_has_no_sent_state(read_env, store, owner) -> None:
    token = mint_token(store)
    post("/api/draft", token, {"revision": "r1", "answers": []}, key(1))
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS[:1]}, key(2))
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(2))
    rows = owner.get(VISITORS, params={"board": SLUG}).json()["visitors"]
    assert [(r["label"], r["revision"]) for r in rows] == [("u1", "r1"), ("u2", "r1")]
    assert all(set(r) == {"label", "number", "revision", "updated_at", "print"} for r in rows)
    assert owner.get(f"{VISITORS}/u/2", params={"board": SLUG, "revision": "r1"}).json() == {"body": {"answers": ANSWERS}}
    assert responses.list_board(response_store(read_env), SLUG) == []


def test_a_draft_needs_a_visitor_key_and_the_revision_the_link_serves(read_env, store) -> None:
    token = mint_token(store)
    assert post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}).json() == {"state": "malformed"}
    got = post("/api/draft", token, {"revision": "r9", "answers": ANSWERS}, key())
    assert (got.status, got.json()) == (409, {"state": "stale"})
    assert drafts.list_board(response_store(read_env), SLUG) == []


@pytest.mark.parametrize("body", [{"revision": "r1", "answers": [{"prompt": "extra", "text": "a‮b"}]},
                                  {"revision": "r1", "answers": [{"prompt": "extra", "text": "x" * 4001}]},
                                  {"revision": "r1", "answers": [{"prompt": "layout"}] * 41},
                                  {"revision": "r1", "answers": [], "name": "sam"}])
def test_a_draft_meets_the_visitor_text_rule_and_the_size_caps(read_env, store, body) -> None:
    token = mint_token(store)
    assert post("/api/draft", token, body, key()).json() == {"state": "malformed"}
    assert drafts.list_board(response_store(read_env), SLUG) == []


def test_a_draft_that_does_not_fit_the_revision_is_rejected(read_env, store) -> None:
    token = mint_token(store)
    got = post("/api/draft", token, {"revision": "r1", "answers": [{"prompt": "layout", "options": ["zz"]}]}, key())
    assert (got.status, got.json()) == (422, {"state": "rejected"})


def test_a_link_takes_at_most_twenty_visitors(read_env, store) -> None:
    token = mint_token(store)
    WRITER.bind(WRITER.deps, drafts_per_min=1000)
    for n in range(drafts.MAX_VISITORS_PER_LINK):
        assert post("/api/draft", token, {"revision": "r1", "answers": []}, key(n)).status == 200
    got = post("/api/draft", token, {"revision": "r1", "answers": []}, key(99))
    assert (got.status, got.json()) == (507, {"state": "full"})
    assert post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(0)).status == 200


def test_a_visitor_cannot_read_another_visitors_answers(read_env, store) -> None:
    token = mint_token(store)
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(1))
    assert board(token, key(2)).json()["draft"] is None
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS[1:]}, key(2))
    assert board(token, key(2)).json()["draft"] == {"body": {"answers": ANSWERS[1:]}}


def test_a_draft_names_the_boards_visitors_topic_only_when_it_changed(read_env, store, monkeypatch) -> None:
    from src.cplugs.reviewboard.public import announce
    told: List[str] = []
    monkeypatch.setattr(announce, "changed", lambda ctx, board: told.append(board))
    token = mint_token(store)
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(1))
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(1))
    assert told == [SLUG]


def test_the_listing_print_moves_when_the_answers_change_even_inside_one_second(read_env, store, monkeypatch) -> None:
    monkeypatch.setattr(drafts.time, "time", lambda: 1_793_000_000.4)
    response_store = responses.storage_for(read_env.host.storage("reviewboard").path)
    token = mint_token(store)
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS[:1]}, key(1))
    first = drafts.list_board(response_store, SLUG)[0]
    post("/api/draft", token, {"revision": "r1", "answers": [{"prompt": "layout", "options": ["a"]}]}, key(1))
    second = drafts.list_board(response_store, SLUG)[0]
    assert first.updated_at == second.updated_at and second.print != first.print
    assert len(first.print) == 8 and all(c in "0123456789abcdef" for c in first.print)



def next_rev(token: str, shown: str) -> Any:
    return get(edge(), "/api/next", token, extra=(("Carnivore-Revision", shown),))


def test_a_pinned_link_answers_fixed_at_once(read_env, store, folder) -> None:
    token = mint_token(store)
    add_revision(folder, b"<!doctype html><title>bar</title><main>second</main>")
    got = next_rev(token, "r1")
    assert (got.status, got.json(), got.headers.get("connection")) == (200, {"state": "fixed", "retry": 10}, "close")


def test_a_follow_link_answers_newer_once_the_newer_revision_is_cleared(read_env, store, folder) -> None:
    token = mint_token(store, mode="follow")
    add_revision(folder, b"<!doctype html><title>bar</title><main>second</main>")
    assert next_rev(token, "r1").json() == {"state": "newer", "revision": "r2"}


def test_a_held_wait_wakes_on_the_boards_push_not_a_timer(read_env, store, folder, monkeypatch) -> None:
    token = mint_token(store, mode="follow")
    followers: List[Callable[[], None]] = []
    resolver = READER.resolver
    assert resolver is not None
    monkeypatch.setattr(resolver, "deps", dataclasses.replace(resolver.deps, follow=lambda listener: (followers.append(listener), lambda: None)[1]))

    async def scenario() -> Any:
        held = asyncio.create_task(call(edge(), "/api/next", token, extra=(("Carnivore-Revision", "r1"),)))
        while not followers:
            await asyncio.sleep(0.01)
        add_revision(folder, b"<!doctype html><title>bar</title><main>second</main>")
        followers[0]()
        return await asyncio.wait_for(held, 3)

    assert asyncio.run(scenario()).json() == {"state": "newer", "revision": "r2"}


def test_a_held_wait_on_a_revoked_link_answers_ended(read_env, store) -> None:
    token = mint_token(store, mode="follow")
    links.revoke_board(store, SLUG)
    assert next_rev(token, "r1").json() == {"state": "ended"}

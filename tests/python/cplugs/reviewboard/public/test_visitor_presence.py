
from __future__ import annotations

import json
import time
from typing import Any, Iterator, List, Optional

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.plugins.reviewboard.public import drafts, presence, waiting, wiring
from src.plugins.reviewboard.public.presence import Presence
from tests.python.cplugs.reviewboard.public.read_harness import edge, get, mint_token
from tests.python.cplugs.reviewboard.boards import SIDECAR

SLUG = SIDECAR["board"]["slug"]
ANSWERS = [{"prompt": "padding", "checked": True}]


def key(n: int) -> str:
    return f"{n:04d}" + "k" * 18


def ask(token: str, visitor: Optional[str], path: str = "/api/next") -> Any:
    extra = [("Carnivore-Revision", "r1")] + ([("Carnivore-Visitor", visitor)] if visitor else [])
    return get(edge(), path, token, extra=tuple(extra))


def answer_once(token: str, visitor: str) -> None:
    out = get(edge(), "/api/draft", token, method="POST", body=json.dumps({"revision": "r1", "answers": ANSWERS}).encode(), extra=(("Carnivore-Visitor", visitor),))
    assert out.status == 200


@pytest.fixture(autouse=True)
def fresh_presence(monkeypatch: pytest.MonkeyPatch) -> Iterator[Presence]:
    own = Presence()
    monkeypatch.setattr(presence, "PRESENCE", own)
    yield own


@pytest.fixture
def owner(read_env: Any) -> Iterator[TestClient]:
    read_env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(read_env.app) as client:
        yield client
    read_env.app.dependency_overrides.clear()


def listing(owner: TestClient) -> Any:
    return owner.get(f"/api/v1/cplugs/reviewboard/public/visitors?board={SLUG}").json()



def test_the_store_counts_an_ask_expires_it_and_says_what_changed() -> None:
    p = Presence(ttl_s=20)
    assert p.touch("bar", ("L1", "aa"), 100.0) is True and p.touch("bar", ("L1", "aa"), 110.0) is False
    assert p.present("bar", 125.0) == [("L1", "aa")] and p.present("other", 125.0) == []
    assert p.expire(125.0) == set() and p.expire(131.0) == {"bar"} and not p.any()
    assert p.touch("bar", ("L1", "aa"), 200.0) is True


def test_the_store_says_how_long_until_the_next_visitor_lapses() -> None:
    p = Presence(ttl_s=20)
    assert p.next_expiry(0.0) is None
    p.touch("bar", ("L1", "aa"), 100.0)
    p.touch("bar", ("L2", "bb"), 110.0)
    assert p.next_expiry(105.0) == 15.0 and p.next_expiry(115.0) == 5.0 and p.next_expiry(125.0) == 0.0


def test_one_link_cannot_hold_more_viewers_than_it_may_have_visitors() -> None:
    p = Presence()
    assert presence.MAX_PER_LINK == drafts.MAX_VISITORS_PER_LINK
    told = [p.touch("bar", ("L1", str(n)), 1.0) for n in range(presence.MAX_PER_LINK + 5)]
    assert told == [True] * presence.MAX_PER_LINK + [False] * 5
    assert len(p.present("bar", 2.0)) == presence.MAX_PER_LINK
    assert p.touch("bar", ("L2", "x"), 1.0) is True
    assert p.touch("bar", ("L1", "0"), 3.0) is False and ("L1", "0") in p.present("bar", 3.5)


def test_the_store_is_bounded_and_drops_the_oldest() -> None:
    p = Presence(ttl_s=1000, limit=3)
    for n in range(5):
        p.touch("bar", ("L", str(n)), float(n))
    assert [who[1] for who in p.present("bar", 10.0)] == ["2", "3", "4"]



def test_a_visitor_that_asks_is_viewing_and_leaves_when_it_stops(read_env, store, owner, fresh_presence) -> None:
    token = mint_token(store)
    answer_once(token, key(1))
    assert listing(owner)["present"] == [] and listing(owner)["viewing"] == 0
    assert ask(token, key(1)).status == 200
    body = listing(owner)
    assert body["present"] == [1] and body["viewing"] == 0
    fresh_presence.expire(time.monotonic() + 30)
    body = listing(owner)
    assert body["present"] == [] and body["viewing"] == 0


def test_a_visitor_with_no_answers_yet_is_counted_as_viewing_without_a_number(read_env, store, owner) -> None:
    token = mint_token(store)
    ask(token, key(7))
    assert listing(owner) == {**listing(owner), "present": [], "viewing": 1}


def test_two_browsers_on_one_link_are_two_viewers(read_env, store, owner) -> None:
    token = mint_token(store)
    answer_once(token, key(1))
    ask(token, key(1))
    ask(token, key(2))
    body = listing(owner)
    assert body["present"] == [1] and body["viewing"] == 1


def test_the_page_of_a_pinned_link_is_told_to_ask_again(read_env, store) -> None:
    body = ask(mint_token(store), key(1)).json()
    assert body == {"state": "fixed", "retry": presence.BEAT_S}


def test_an_ask_with_no_key_or_no_link_is_never_counted(read_env, store, owner) -> None:
    token = mint_token(store)
    ask(token, None)
    ask("pbl_garbage.secret", key(1))
    assert listing(owner)["viewing"] == 0 and listing(owner)["present"] == []


def test_the_key_itself_is_never_held(read_env, store, fresh_presence) -> None:
    token = mint_token(store)
    ask(token, key(3))
    held = [who for mine in fresh_presence._seen.values() for who in mine]
    assert held and all(key(3) not in part for who in held for part in who)
    assert held[0][1] == drafts.key_hash(key(3))


def test_a_follow_links_held_wait_is_a_beat_too(read_env, store, owner, monkeypatch) -> None:
    monkeypatch.setattr(waiting, "HOLD_S", 0.05)
    token = mint_token(store, mode="follow")
    answer_once(token, key(1))
    assert ask(token, key(1)).json() == {"state": "same"}
    assert listing(owner)["present"] == [1]



def test_the_owner_is_told_on_arrival_and_on_lapse_and_not_on_every_ask(read_env, store, fresh_presence, monkeypatch) -> None:
    told: List[str] = []
    monkeypatch.setattr(wiring.announce, "changed", lambda ctx, board: told.append(board))
    token = mint_token(store)
    ask(token, key(1))
    ask(token, key(1))
    assert told == [SLUG]
    wiring.sweep_presence(read_env.host.context("reviewboard", background=True), time.monotonic() + 30)
    assert told == [SLUG, SLUG]

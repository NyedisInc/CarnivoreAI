
from __future__ import annotations

import asyncio
import dataclasses
import json
import sqlite3
import time
import uuid
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, List, Optional

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.reviewboard.public import drafts, links, responses, theme, waiting
from src.cplugs.reviewboard.public.read import READER
from src.cplugs.reviewboard.public.resolve import Resolver
from src.cplugs.sdk.storage import CplugStorage, StorageSpec
from tests.python.cplugs.reviewboard.public.read_harness import add_revision, call, edge, get, mint_token, rewrite

SLUG = "20261013-bottom-bar"
VISITORS = "/api/v1/cplugs/reviewboard/public/visitors"
LINKS = "/api/v1/cplugs/reviewboard/public/links"
ANSWERS = [{"prompt": "layout", "options": ["b"]}, {"prompt": "padding", "checked": True}]
SECOND = b"<!doctype html><title>bar</title><main>second</main>"


def key(n: int = 0) -> str:
    return f"{n:04d}" + "k" * 18


def post(path: str, token: str, body: Dict[str, Any], visitor: Optional[str] = None) -> Any:
    extra = (("Carnivore-Visitor", visitor),) if visitor else ()
    return get(edge(), path, token, method="POST", body=json.dumps(body).encode(), extra=extra)


def board(token: str, visitor: Optional[str] = None) -> Any:
    return get(edge(), "/api/board", token, extra=(("Carnivore-Visitor", visitor),) if visitor else ())


def rstore(read_env: Any) -> Any:
    return responses.storage_for(read_env.host.storage("reviewboard").path)


def draft_rows(read_env: Any) -> List[tuple]:
    return [(row.number, row.revision) for row in drafts.list_board(rstore(read_env), SLUG)]


def rebind(**limits: int) -> Resolver:
    assert READER.resolver is not None
    READER.resolver = Resolver(READER.resolver.deps, **limits)
    return READER.resolver


@pytest.fixture
def owner(read_env: Any) -> Iterator[TestClient]:
    read_env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(read_env.app) as client:
        yield client
    read_env.app.dependency_overrides.clear()



def test_a_visitor_keeps_answering_the_revision_they_saw_after_a_follow_link_moves(read_env, store, folder) -> None:
    token = mint_token(store, mode="follow")
    assert post("/api/draft", token, {"revision": "r1", "answers": ANSWERS[:1]}, key(1)).status == 200
    add_revision(folder, SECOND)
    assert board(token).json()["revision"] == "r2"
    assert post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(1)).json() == {"state": "saved", "changed": True}
    assert responses.list_board(rstore(read_env), SLUG) == []
    assert draft_rows(read_env) == [(1, "r1")]


def test_a_revision_the_link_never_served_is_stale(read_env, store, folder) -> None:
    add_revision(folder, SECOND)
    token = mint_token(store)
    for path, body in (("/api/draft", {"revision": "r1", "answers": ANSWERS}),
                       ("/api/comments", {"client_post_id": uuid.uuid4().hex, "revision": "r9", "text": "hello"})):
        got = post(path, token, body, key())
        assert (got.status, got.json()) == (409, {"state": "stale"}), path
    assert responses.list_board(rstore(read_env), SLUG) == [] and draft_rows(read_env) == []


def test_a_comment_names_its_revision_too(read_env, store, folder) -> None:
    token = mint_token(store, mode="follow")
    add_revision(folder, SECOND)
    board(token)
    assert post("/api/comments", token, {"client_post_id": uuid.uuid4().hex, "revision": "r1", "text": "the r1 row"}, key()).status == 201
    assert [r.revision for r in responses.list_board(rstore(read_env), SLUG)] == ["r1"]



def test_autosaves_do_not_spend_the_links_read_budget(read_env, store) -> None:
    rebind(per_link=3, per_client=1000)
    token = mint_token(store)
    for n in range(6):
        assert post("/api/draft", token, {"revision": "r1", "answers": []}, key(n % 3)).status == 200, n
    assert board(token).status == 200


def test_autosaves_and_waits_do_not_spend_the_addresss_read_budget(read_env, store) -> None:
    rebind(per_client=3, per_link=1000)
    token = mint_token(store)
    for n in range(3):
        assert post("/api/draft", token, {"revision": "r1", "answers": []}, key(n)).status == 200
        assert get(edge(), "/api/next", token, extra=(("Carnivore-Revision", "r1"),)).status == 200
    assert board(token).status == 200


def test_the_background_budget_is_bounded_and_says_when_to_come_back(read_env, store) -> None:
    rebind(background_per_link=2)
    token = mint_token(store)
    assert [post("/api/draft", token, {"revision": "r1", "answers": []}, key(n)).status for n in range(3)] == [200, 200, 429]
    assert post("/api/draft", token, {"revision": "r1", "answers": []}, key(5)).headers.get("retry-after") == "30"



def _hold_with_pushes(monkeypatch: pytest.MonkeyPatch) -> List[Callable[[], None]]:
    followers: List[Callable[[], None]] = []
    resolver = READER.resolver
    assert resolver is not None

    def follow(listener: Callable[[], None]) -> Callable[[], None]:
        followers.append(listener)
        return lambda: followers.remove(listener) if listener in followers else None

    monkeypatch.setattr(resolver, "deps", dataclasses.replace(resolver.deps, follow=follow))
    return followers


def _count_rechecks(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    resolver = READER.resolver
    assert resolver is not None
    seen: List[str] = []
    real = resolver.recheck

    async def counted(link_id: str) -> Any:
        seen.append(link_id)
        return await real(link_id)

    monkeypatch.setattr(resolver, "recheck", counted)
    return seen


def test_one_board_change_costs_one_recheck_per_link_however_many_wait(read_env, store, folder, monkeypatch) -> None:
    token = mint_token(store, mode="follow")
    followers = _hold_with_pushes(monkeypatch)
    seen = _count_rechecks(monkeypatch)

    async def scenario() -> List[Any]:
        held = [asyncio.create_task(call(edge(), "/api/next", token, extra=(("Carnivore-Revision", "r1"),))) for _ in range(3)]
        while len(followers) < 3:
            await asyncio.sleep(0.01)
        add_revision(folder, SECOND)
        for listener in list(followers):
            listener()
        return await asyncio.wait_for(asyncio.gather(*held), 5)

    assert [a.json() for a in asyncio.run(scenario())] == [{"state": "newer", "revision": "r2"}] * 3
    assert len(seen) == 1


def test_a_change_that_leaves_this_boards_newest_revision_alone_costs_no_recheck(read_env, store, monkeypatch) -> None:
    monkeypatch.setattr(waiting, "HOLD_S", 0.6)
    token = mint_token(store, mode="follow")
    followers = _hold_with_pushes(monkeypatch)
    seen = _count_rechecks(monkeypatch)

    async def scenario() -> Any:
        held = asyncio.create_task(call(edge(), "/api/next", token, extra=(("Carnivore-Revision", "r1"),)))
        while not followers:
            await asyncio.sleep(0.01)
        for _ in range(2):
            followers[0]()
            await asyncio.sleep(0.05)
        return await asyncio.wait_for(held, 3)

    assert asyncio.run(scenario()).json() == {"state": "same"}
    assert seen == []


def test_a_newer_revision_is_scanned_once_however_many_read_it_at_once(read_env, store, folder, monkeypatch) -> None:
    token = mint_token(store, mode="follow")
    add_revision(folder, SECOND)
    resolver = READER.resolver
    assert resolver is not None
    scans: List[int] = []
    real = resolver.deps.scan

    def slow_scan(texts: Any) -> Any:
        if any("second" in text for text in texts):
            scans.append(1)
            time.sleep(0.2)
        return real(texts)

    monkeypatch.setattr(resolver, "deps", dataclasses.replace(resolver.deps, scan=slow_scan))

    async def scenario() -> List[Any]:
        return await asyncio.gather(*(call(edge(), "/api/board", token) for _ in range(4)))

    assert [a.json()["revision"] for a in asyncio.run(scenario())] == ["r2"] * 4
    assert len(scans) == 1



def test_the_owner_lists_summaries_and_opens_one_body(read_env, store, owner) -> None:
    token = mint_token(store)
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(1))
    rows = owner.get(VISITORS, params={"board": SLUG}).json()["visitors"]
    assert rows == [{"label": "u1", "number": 1, "revision": "r1", "updated_at": rows[0]["updated_at"], "print": rows[0]["print"]}] and len(rows[0]["print"]) == 8
    got = owner.get(f"{VISITORS}/u/1", params={"board": SLUG, "revision": "r1"})
    assert got.status_code == 200 and got.json() == {"body": {"answers": ANSWERS}}
    assert owner.get(f"{VISITORS}/u/2", params={"board": SLUG, "revision": "r1"}).status_code == 404


def test_the_owner_removes_one_u_revision_or_the_whole_visitor(read_env, store, owner, monkeypatch) -> None:
    from src.cplugs.reviewboard.public import announce
    told: List[str] = []
    monkeypatch.setattr(announce, "changed", lambda ctx, board: told.append(board))
    token = mint_token(store)
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(1))
    post("/api/draft", token, {"revision": "r1", "answers": []}, key(2))
    told.clear()
    assert owner.delete(f"{VISITORS}/u/1", params={"board": SLUG, "revision": "r1"}).json() == {"removed": 1}
    assert draft_rows(read_env) == [(2, "r1")] and told == [SLUG]
    assert owner.delete(f"{VISITORS}/u/2", params={"board": SLUG}).json() == {"removed": 1}
    assert draft_rows(read_env) == []
    assert owner.delete(f"{VISITORS}/u/2", params={"board": SLUG}).json() == {"removed": 0}



def test_a_theme_with_too_many_names_is_trimmed_not_refused(read_env, owner) -> None:
    palette = {f"--oc-t{n:03d}": "#123456" for n in range(700)}
    made = owner.post(LINKS, json={"board": SLUG, "ttl": "1d", "theme": palette})
    assert made.status_code == 201
    assert len(board(made.json()["token"]).json()["theme"]) == theme.MAX_VARS


def test_a_theme_over_the_frames_byte_limit_is_trimmed_to_fit(read_env, owner) -> None:
    palette = {f"--oc-t{n:03d}": "a" * 200 for n in range(400)}
    made = owner.post(LINKS, json={"board": SLUG, "ttl": "1d", "theme": palette})
    kept = board(made.json()["token"]).json()["theme"]
    assert 0 < len(json.dumps(kept, separators=(",", ":"))) <= theme.MAX_BYTES



def test_an_expired_link_refuses_a_draft(read_env, store, monkeypatch) -> None:
    token = mint_token(store, ttl="1h")
    later = time.time() + 7200
    monkeypatch.setattr(links, "time", SimpleNamespace(time=lambda: later))
    got = post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key())
    assert (got.status, got.json()) == (404, {"state": "ended"})
    assert draft_rows(read_env) == []


def test_a_payload_page_autosaves_its_payload(read_env, store, folder) -> None:
    def payload_page(raw: Dict[str, Any]) -> None:
        raw["revisions"][0].update(payload_mode=True, prompts=[], anchors=[])
        raw["rounds"] = []
        for rev in raw["revisions"]:
            rev["answers_round"] = None

    rewrite(folder, payload_page)
    token = mint_token(store)
    body = {"revision": "r1", "payload": {"pick": "b", "note": "keep"}}
    assert post("/api/draft", token, body, key(1)).json() == {"state": "saved", "changed": True}
    assert board(token, key(1)).json()["draft"] == {"body": {"payload": body["payload"]}}
    assert board(token, key(2)).json()["draft"] is None


def test_the_hold_caps_count_per_link_and_in_all() -> None:
    held = waiting.Waiters()
    assert all(held.admit("a") for _ in range(waiting.MAX_HELD_PER_LINK)) and not held.admit("a")
    assert all(held.admit("b") for _ in range(waiting.MAX_HELD - waiting.MAX_HELD_PER_LINK)) and not held.admit("c")
    held.leave("a")
    assert held.admit("c") and not held.admit("c")


def test_a_full_listener_answers_same_with_a_retry(read_env, store, monkeypatch) -> None:
    token = mint_token(store, mode="follow")
    monkeypatch.setattr(waiting, "WAITERS", SimpleNamespace(admit=lambda link_id: False, leave=lambda link_id: None))
    got = get(edge(), "/api/next", token, extra=(("Carnivore-Revision", "r1"),))
    assert got.json() == {"state": "same", "retry": waiting.BUSY_RETRY_S}


def test_a_quiet_hold_answers_same_when_it_ends(read_env, store, monkeypatch) -> None:
    monkeypatch.setattr(waiting, "HOLD_S", 0.05)
    token = mint_token(store, mode="follow")
    assert get(edge(), "/api/next", token, extra=(("Carnivore-Revision", "r1"),)).json() == {"state": "same"}


def test_version_one_files_holding_rows_migrate_to_version_two(tmp_path) -> None:
    folder = tmp_path / "plugin"
    folder.mkdir(mode=0o700)
    for name, ladder, row in (("links.db", links.MIGRATIONS, "INSERT INTO links VALUES ('id1', 'h', 'b', 'r1', 'follow', 1, 2, NULL, 'x')"),
                              ("responses.db", responses.MIGRATIONS,
                               "INSERT INTO responses (link_id, board, revision, kind, name, body, client_post_id, created_at) "
                               "VALUES ('id1', 'b', 'r1', 'comment', NULL, '{}', 'p1', 1)")):
        with sqlite3.connect(folder / name) as conn:
            conn.executescript(ladder[0])
            conn.execute(row)
            conn.execute("PRAGMA user_version = 1")
        storage = CplugStorage(folder, StorageSpec(db=name, migrations=ladder, private=True))
        with storage.connect(False) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == len(ladder)
    assert [(link.access, link.theme) for link in links.list_links(CplugStorage(folder, StorageSpec(db="links.db", migrations=links.MIGRATIONS, private=True)))] == [("answer", None)]
    assert links.served(CplugStorage(folder, StorageSpec(db="links.db", migrations=links.MIGRATIONS, private=True)), "id1", "r1")
    with sqlite3.connect(folder / "responses.db") as conn:
        assert conn.execute("SELECT visitor FROM responses").fetchall() == [(None,)]

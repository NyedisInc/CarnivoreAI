
from __future__ import annotations

import asyncio
import dataclasses
import os
import shutil
import sqlite3
import time
import uuid
from types import SimpleNamespace
from typing import Any, List

import pytest
import structlog
import structlog.testing

from src.cplugs.reviewboard.public import lifecycle
from src.cplugs.reviewboard.public.service import SERVICE
from src.cplugs.reviewboard.public import drafts, ratelimit, wiring
from src.cplugs.reviewboard.public.read import READER
from src.cplugs.reviewboard.public.write import WRITER
from tests.python.cplugs.reviewboard.public.read_harness import mint_token
from tests.python.cplugs.reviewboard.public.test_visitor_revision_rules import ANSWERS, SLUG, VISITORS, key, owner, post, rstore  # noqa: F401


def age(read_env: Any, number: int) -> None:
    old = int(time.time()) - drafts.RETENTION_S - 1
    with sqlite3.connect(rstore(read_env).db_path) as conn:
        conn.execute("UPDATE drafts SET updated_at = ? WHERE visitor = (SELECT id FROM visitors WHERE number = ?)", (old, number))
        conn.execute("UPDATE visitors SET created_at = ? WHERE number = ?", (old, number))


def numbers(read_env: Any) -> List[int]:
    with sqlite3.connect(rstore(read_env).db_path) as conn:
        return [r[0] for r in conn.execute("SELECT number FROM visitors ORDER BY number")]



def test_the_owners_listing_no_longer_writes(read_env, store, owner) -> None:
    token = mint_token(store)
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(1))
    age(read_env, 1)
    owner.get(VISITORS, params={"board": SLUG})
    assert numbers(read_env) == [1]


def test_plugin_start_drops_what_is_past_the_retention_on_a_board_never_listed(read_env, store, monkeypatch) -> None:
    token = mint_token(store)
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(1))
    age(read_env, 1)

    async def no_listener(settings: Any) -> None:
        pass

    monkeypatch.setattr(SERVICE, "apply", no_listener)
    asyncio.run(lifecycle.start(read_env.host.context("reviewboard", background=True)))
    assert numbers(read_env) == []


def test_the_write_path_drops_what_is_past_the_retention_at_most_hourly(read_env, store, monkeypatch) -> None:
    clock = SimpleNamespace(now=10_000.0)
    monkeypatch.setattr(wiring, "time", SimpleNamespace(monotonic=lambda: clock.now, time=time.time))
    WRITER.bind(wiring.build_write(read_env.host.context("reviewboard", background=True)))
    token = mint_token(store)
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(1))
    age(read_env, 1)
    post("/api/draft", token, {"revision": "r1", "answers": []}, key(2))
    assert numbers(read_env) == [1, 2]
    clock.now += wiring.PRUNE_EVERY_S + 1
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(2))
    assert numbers(read_env) == [2]



def _count_reads(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    resolver = READER.resolver
    assert resolver is not None
    reads: List[str] = []
    real = resolver.deps.revision

    def counted(board: str, revision: str, view: Any) -> Any:
        reads.append(revision)
        return real(board, revision, view)

    monkeypatch.setattr(resolver, "deps", dataclasses.replace(resolver.deps, revision=counted))
    return reads


def test_an_autosave_reads_no_revision_through_the_resolver(read_env, store, monkeypatch) -> None:
    token = mint_token(store)
    reads = _count_reads(monkeypatch)
    assert post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(1)).status == 200
    assert reads == []


def test_a_junk_autosave_past_the_visitor_limit_costs_no_board_read(read_env, store, monkeypatch) -> None:
    WRITER.bind(WRITER.deps, drafts_per_min=1)
    token = mint_token(store)
    reads = _count_reads(monkeypatch)
    assert post("/api/draft", token, {"nope": 1}, key(1)).json() == {"state": "malformed"}
    assert post("/api/draft", token, {"revision": "r1", "answers": []}, key(1)).json() == {"state": "limited"}
    assert reads == []


def test_the_background_budget_per_address_covers_two_people_and_no_more() -> None:
    assert ratelimit.BACKGROUND_PER_CLIENT_PER_MIN == 120



def test_a_removed_visitors_number_is_never_given_to_another(read_env, store, owner) -> None:
    token = mint_token(store)
    post("/api/draft", token, {"revision": "r1", "answers": []}, key(1))
    post("/api/draft", token, {"revision": "r1", "answers": []}, key(2))
    owner.delete(f"{VISITORS}/u/2", params={"board": SLUG})
    post("/api/draft", token, {"revision": "r1", "answers": []}, key(3))
    assert numbers(read_env) == [1, 3]


def test_a_pruned_visitors_number_is_never_given_to_another(read_env, store) -> None:
    token = mint_token(store)
    post("/api/draft", token, {"revision": "r1", "answers": []}, key(1))
    age(read_env, 1)
    drafts.prune(rstore(read_env))
    post("/api/draft", token, {"revision": "r1", "answers": ANSWERS}, key(2))
    assert numbers(read_env) == [2]



@pytest.mark.parametrize("answers", [ANSWERS, []], ids=["with_answers", "empty"])
def test_an_autosave_to_a_removed_board_answers_ended_and_stores_nothing(read_env, store, folder, answers) -> None:
    token = mint_token(store)
    shutil.rmtree(folder)
    got = post("/api/draft", token, {"revision": "r1", "answers": answers}, key(1))
    assert (got.status, got.json()) == (404, {"state": "ended"})
    db = rstore(read_env).db_path
    if os.path.exists(db):
        with sqlite3.connect(db) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            for table in {"visitors", "drafts"} & tables:
                assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


@pytest.mark.parametrize("path, body, visitors", [("/api/draft", {"revision": "r1", "answers": ANSWERS}, [1]), ("/api/comments", {"text": "hi"}, [])],
                         ids=["draft", "comment"])
def test_a_failed_hourly_cleanup_after_a_stored_write_keeps_the_write_answer(read_env, store, monkeypatch, path, body, visitors) -> None:
    clock = SimpleNamespace(now=10_000.0)
    monkeypatch.setattr(wiring, "time", SimpleNamespace(monotonic=lambda: clock.now, time=time.time))

    def broken(store: Any) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(drafts, "prune", broken)
    WRITER.bind(wiring.build_write(read_env.host.context("reviewboard", background=True)))
    token = mint_token(store)
    clock.now += wiring.PRUNE_EVERY_S + 1
    with structlog.testing.capture_logs() as logs:
        got = post(path, token, {**body, **({"client_post_id": str(uuid.uuid4())} if path == "/api/comments" else {})}, key(1))
    assert got.status in (200, 201), got.body
    assert numbers(read_env) == visitors
    failed = [e for e in logs if e["event"] == "publicboard_prune_failed"]
    assert failed and failed[0]["where"] == "write"

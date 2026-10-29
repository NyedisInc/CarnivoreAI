
from __future__ import annotations

import json
from contextlib import closing

import pytest

from tests.python.deepsearch.helpers import build_world, cq, drain, scan, teardown

from src.core.deepsearch import constants as K
from src.core.deepsearch import search
from src.core.deepsearch.cache import db as cache_db
from src.core.deepsearch.cache import flip


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    tool_call = {"type": "assistant", "uuid": "t-1", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "x1", "name": "Bash", "input": {"command": "grep toolonlyword f"}}]}}
    tool_out = {"type": "user", "uuid": "t-2", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x1", "content": "resultonlyword"}]}}
    with open(built["main"], "ab") as handle:
        handle.write(b"".join((json.dumps(x) + "\n").encode() for x in (tool_call, tool_out)))
    yield built
    teardown()


def _hits(world, words):
    with closing(cache_db.reader(world["state"])) as conn:
        return search.search(conn, world["state"], words, overrides={})["hits"]


def test_cache_holds_only_said_text_flips_when_complete_and_rebuilds_after_a_delete(world):
    assert flip.state(world["state"]) == K.CACHE_BUILDING and not _hits(world, "wombatmain")

    scan(world)
    drain(world)
    assert {r[0] for r in cq(world, f"SELECT DISTINCT kind FROM {K.ROWS_TABLE}")} == {K.KIND_USER, K.KIND_ASSISTANT}
    assert cq(world, f"SELECT COUNT(*) FROM {K.ROWS_TABLE}")[0][0] == 5
    assert flip.state(world["state"]) == K.CACHE_READY
    (hit, *_rest) = _hits(world, "wombatmain")
    assert {h["line"] for h in _hits(world, "wombatmain")} == {0, 1} and "\x02wombatmain\x03" in hit["snippet"]
    assert not _hits(world, "toolonlyword") and not _hits(world, "resultonlyword")

    flip.reset(world["state"])
    assert flip.state(world["state"]) == K.CACHE_BUILDING
    assert cq(world, f"SELECT COUNT(*) FROM {K.ROWS_TABLE}")[0][0] == 0
    assert not _hits(world, "wombatmain")
    scan(world)
    drain(world)
    scan(world)
    assert flip.state(world["state"]) == K.CACHE_READY
    assert cq(world, f"SELECT COUNT(*) FROM {K.ROWS_TABLE}")[0][0] == 5
    assert {h["line"] for h in _hits(world, "wombatmain")} == {0, 1}


def test_a_project_move_forgets_the_cache_files_under_the_moved_folder_only(tmp_path):
    from src.core.project_move.transcript_rekey import forget_moved_in_cache
    from src.core.deepsearch.live import store

    with closing(cache_db.open_cache(tmp_path)) as conn:
        for path in ("/x/old/a.jsonl", "/x/older/b.jsonl"):
            store.save(conn, store.LiveFile("c", path, "conversation", "claude", 0, 0, None, 5, 1, None, None, 1, "v",
                                            1, "human", "2026-10-12", "2026-10-12"))
    assert forget_moved_in_cache(tmp_path, [{"from": "/x/old", "to": "/x/new", "mode": "rename"}]) == 1
    with closing(cache_db.open_cache(tmp_path)) as conn:
        assert [r[0] for r in conn.execute(f"SELECT path FROM {K.LIVE_TABLE}")] == ["/x/older/b.jsonl"]


def test_a_many_conversation_build_indexes_every_file_and_keeps_redaction(world):
    secret = "sk-ant-api03-" + "Ab1" * 20
    folder = world["main"].parent
    count = 24
    for i in range(count):
        text = f"batchword{i} " + (f"token {secret}" if i == 0 else "plain")
        (folder / f"00000000-0000-4000-8000-{i:012d}.jsonl").write_bytes(
            json.dumps({"type": "user", "uuid": f"b-{i}", "message": {"role": "user", "content": text}}).encode() + b"\n")
    scan(world)
    drain(world)
    scan(world)
    assert flip.state(world["state"]) == K.CACHE_READY
    assert cq(world, f"SELECT COUNT(*) FROM {K.ROWS_TABLE}")[0][0] == 5 + count
    assert cq(world, f"SELECT COUNT(*) FROM {K.FTS_TABLE} WHERE {K.FTS_TABLE} MATCH 'batchword0'")[0][0] == 1
    assert cq(world, f"SELECT COUNT(*) FROM {K.FTS_TABLE} WHERE {K.FTS_TABLE} MATCH 'Ab1Ab1Ab1Ab1Ab1Ab1'")[0][0] == 0

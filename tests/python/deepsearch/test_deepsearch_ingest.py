
from __future__ import annotations

import json
from contextlib import closing

import pytest

from tests.python.deepsearch.helpers import SUBAGENT_WORDS, build_world, cq, drain, go_ready, q, scan, teardown
from tests.python.deepsearch.helpers import switch as set_plugin
from tests.python.transcript_source.helpers import CONV

from src.core.deepsearch import grouped, status  # noqa: E402
from src.core.deepsearch.cache import db as cache_db  # noqa: E402


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    yield built
    teardown()


def _grouped(world, words, **kw):
    go_ready(world)
    with closing(cache_db.reader(world["state"])) as conn:
        return grouped.search_grouped(conn, world["state"], words, overrides={}, **kw)


def _status(world):
    return status.index_status(world["state"])


def test_catchup_indexes_files_that_never_grew_including_every_subagent(world):
    before = _status(world)
    assert before["state"] == "running" and before["coverage"]["subagent"] == {"files": 0, "indexed": 0}
    record = scan(world)
    assert record["grown"] == 0
    drain(world)
    for word in SUBAGENT_WORDS:
        answer = _grouped(world, word)
        assert [g["conversation_id"] for g in answer["groups"]] == [CONV], word
        assert answer["groups"][0]["by_file_kind"] == {"subagent": 1}
        assert answer["groups"][0]["hits"][0]["file_kind"] == "subagent"
        assert f"\x02{word}\x03" in answer["groups"][0]["hits"][0]["snippet"]
    after = _status(world)
    assert after["coverage"]["subagent"] == {"files": 3, "indexed": 3}
    assert after["coverage"]["conversation"] == {"files": 1, "indexed": 1}
    assert after["coverage"]["backlog_files"] == 0 and after["newest_indexed_at"] is not None


def test_a_stored_off_switch_is_ignored_and_save_off_does_not_stall_the_index(world):
    set_plugin(world["state"], "save", False)
    scan(world)
    drain(world)
    state = _status(world)
    assert state["state"] == status.STATE_RUNNING and state["reason"] is None
    assert _grouped(world, "wombatmain")["total_conversations"] == 1

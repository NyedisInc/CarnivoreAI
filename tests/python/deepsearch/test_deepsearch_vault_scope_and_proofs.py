
from __future__ import annotations

from contextlib import closing

from tests.python.deepsearch.helpers import SUBAGENT_WORDS, cq, drain, go_ready, rec, scan
from tests.python.deepsearch.helpers import choose_scope
from tests.python.deepsearch.test_deepsearch_vault_read import (  # noqa: F401
    _again, _capture, _delete_conversation, _groups, _register, rig)
from tests.python.transcript_source.helpers import CONV

from src.core.deepsearch import constants as K
from src.core.deepsearch import scope_reconcile
from src.core.deepsearch.cache import db as cache_db


def _settle(rig) -> int:
    with closing(cache_db.open_cache(rig.world["state"])) as conn:
        return scope_reconcile.settle(conn, sleep=lambda _s: None)


def _index_from_disk(rig) -> None:
    scan(rig.world)
    drain(rig.world)
    go_ready(rig.world)


def test_narrowing_the_scope_judges_a_vault_served_headless_session_by_its_vault_bytes(rig):
    rig.world["main"].write_bytes(rec(0, "a headless run about wombatmain", entrypoint="sdk-cli"))
    _index_from_disk(rig)
    _capture(rig)
    _register(rig)
    _delete_conversation(rig)
    _again(rig)
    assert [g["conversation_id"] for g in _groups(rig.world, "wombatmain")] == [CONV]
    choose_scope(rig.world["state"], "human")
    assert _settle(rig) > 0
    assert _groups(rig.world, "wombatmain") == []
    assert cq(rig.world, f"SELECT COUNT(*) FROM {K.LIVE_TABLE} WHERE in_scope = 1 AND file_kind = 'conversation'") == [(0,)]


def test_narrowing_keeps_a_vault_served_human_session_in_scope(rig):
    _index_from_disk(rig)
    _capture(rig)
    _register(rig)
    _delete_conversation(rig)
    _again(rig)
    choose_scope(rig.world["state"], "human")
    _settle(rig)
    assert [g["conversation_id"] for g in _groups(rig.world, "wombatmain")] == [CONV]
    assert _groups(rig.world, SUBAGENT_WORDS[0]) == []


def test_widening_the_scope_indexes_the_sub_agent_files_of_a_conversation_the_lane_had_settled(rig):
    choose_scope(rig.world["state"], "human")
    scan(rig.world)
    _capture(rig)
    _register(rig)
    _delete_conversation(rig)
    _again(rig)
    assert [g["conversation_id"] for g in _groups(rig.world, "wombatmain")] == [CONV]
    assert _groups(rig.world, SUBAGENT_WORDS[0]) == []
    choose_scope(rig.world["state"], "all")
    _settle(rig)
    _again(rig)
    (sub,) = _groups(rig.world, SUBAGENT_WORDS[0])
    assert sub["hits"] and all(hit["from_backup"] is True for hit in sub["hits"])


def test_a_reused_row_id_is_proven_against_the_vault_again(rig):
    for path in rig.world["subagents"]:
        path.unlink()
    _index_from_disk(rig)
    _capture(rig)
    vault_length = rig.world["main"].stat().st_size
    _register(rig)
    first_id = cq(rig.world, f"SELECT id FROM {K.LIVE_TABLE}")[0][0]
    rig.world["main"].unlink()
    _again(rig)
    _again(rig)
    assert cq(rig.world, f"SELECT id, base_point_id FROM {K.LIVE_TABLE}") == [(first_id, "vault")]
    rig.world["main"].write_bytes(rec(0, "the main conversation talks about wombatmain") + rec(1, "wombatmain again", "assistant")
                                  + rec(2, "a later message about zebrathird"))
    _again(rig)
    assert cq(rig.world, f"SELECT id, base_point_id FROM {K.LIVE_TABLE}") == [(first_id, None)]
    rig.world["main"].unlink()
    _again(rig)
    _again(rig)
    assert _groups(rig.world, "zebrathird") == []
    rows = cq(rig.world, f"SELECT indexed_offset, base_point_id FROM {K.LIVE_TABLE}")
    assert rows == [(vault_length, "vault")]

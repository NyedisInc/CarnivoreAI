
from __future__ import annotations

from contextlib import closing
from types import SimpleNamespace
from typing import List

import pytest

from tests.python.deepsearch.helpers import SUBAGENT_WORDS, build_world, cq, drain, go_ready, rec, scan, teardown
from tests.python.cplugs.save.vault_helpers import CODEX_ID
from tests.python.transcript_source.helpers import CONV

from src.core import claude_transcript_correlate
from src.core.attention import codex_gather
from src.core.deepsearch import constants as K
from src.core.db import connect
from src.core.deepsearch import context, grouped, vault_lane
from src.core.deepsearch.cache import db as cache_db
from src.cplugs.save.fallback import BackupTranscripts
from src.cplugs.save.vault import units
from src.cplugs.save.vault.identity import Identity
from src.cplugs.save.vault.store import Vault
from src.core.deepsearch import fallback_hook as fb

CODEX_LINES = (b'{"type":"event_msg","payload":{"type":"user_message","message":"the codex thread discussed the okapiprotocol"}}\n'
               b'{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"okapiprotocol noted"}]}}\n')


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    world = build_world(tmp_path, monkeypatch)
    monkeypatch.setattr(claude_transcript_correlate, "default_projects_dir", lambda: world["corpus"])
    codex = tmp_path / "codex-home"
    monkeypatch.setattr(codex_gather, "DEFAULT_CODEX_HOME", str(codex))
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "VAULT.json").write_text('{"format": 1}')
    vault_lane.reset()
    fb.end_boot()
    built = SimpleNamespace(world=world, codex=codex, vault=Vault(vault_root), sources=units.Sources((world["corpus"],), codex, world["state"]),
                            source=None)
    built.source = BackupTranscripts(lambda: built.vault)
    yield built
    fb.unregister("vault")
    fb.end_boot()
    vault_lane.reset()
    teardown()


def _capture(rig, codex: bool = False, identity: Identity = Identity()) -> None:
    rig.vault.capture(units.plan_claude(rig.sources, CONV), identity, "backfill")
    if codex:
        rollout = rig.codex / "sessions" / "2026" / "03" / "01" / f"rollout-2026-03-01T10-00-00-{CODEX_ID}.jsonl"
        rollout.parent.mkdir(parents=True, exist_ok=True)
        rollout.write_bytes(CODEX_LINES)
        rig.vault.capture(units.plan_codex(rig.sources, CODEX_ID), Identity(), "backfill")
        rollout.unlink()


def _register(rig) -> None:
    fb.register("vault", rig.source)


def _delete_conversation(rig) -> List[str]:
    gone = [str(rig.world["main"]), *map(str, rig.world["subagents"])]
    for path in gone:
        from pathlib import Path
        Path(path).unlink()
    return gone


def _again(rig) -> None:
    vault_lane._last_listing = float("-inf")
    scan(rig.world)
    drain(rig.world)
    go_ready(rig.world)


def _answer(world, words: str):
    with closing(cache_db.reader(world["state"])) as conn:
        return grouped.search_grouped(conn, world["state"], words, overrides={})


def _groups(world, words: str):
    return _answer(world, words)["groups"]


def _indexed(rig) -> None:
    scan(rig.world)
    drain(rig.world)
    go_ready(rig.world)
    (group,) = _groups(rig.world, "wombatmain")
    assert all(hit["from_backup"] is False for hit in group["hits"])


def test_a_deleted_conversation_stays_searchable_from_the_vault_with_no_second_copy(rig):
    _indexed(rig)
    before = cq(rig.world, f"SELECT id, path, indexed_offset FROM {K.LIVE_TABLE} ORDER BY id")
    _capture(rig)
    _register(rig)
    gone = _delete_conversation(rig)
    _again(rig)
    assert cq(rig.world, f"SELECT id, path, indexed_offset FROM {K.LIVE_TABLE} ORDER BY id") == before
    (group,) = _groups(rig.world, "wombatmain")
    assert group["conversation_id"] == CONV and group["hits"] and all(hit["from_backup"] is True for hit in group["hits"])
    assert "\x02wombatmain\x03" in group["hits"][0]["snippet"]
    (sub,) = _groups(rig.world, SUBAGENT_WORDS[0])
    assert all(hit["from_backup"] is True and hit["file_kind"] == "subagent" for hit in sub["hits"])
    rows = cq(rig.world, f"SELECT path, base_point_id FROM {K.LIVE_TABLE} ORDER BY path")
    assert sorted(path for path, _ in rows) == sorted(gone) and {mark for _, mark in rows} == {"vault"}
    assert not (rig.world["state"] / K.BACKUP_COPY_DIR).exists()
    with closing(cache_db.reader(rig.world["state"])) as conn:
        file = context.find_file(conn, CONV, "conversation")
        window = context.window(file, {}, [], line=1)
    assert file.from_backup and [m["text"] for m in window["messages"]] == [
        "the main conversation talks about wombatmain", "wombatmain again"]
    from src.core.deepsearch.status import index_status
    assert index_status(rig.world["state"])["coverage"]["from_backup"] == {"files": 4, "conversations": 1}


def test_a_vault_served_group_carries_the_name_project_and_folder_the_backup_recorded(rig):
    _indexed(rig)
    with closing(connect(rig.world["db"], create=False)) as main_db:
        main_db.execute("DELETE FROM sessions WHERE claude_session_uuid = ?", (CONV,))
    _capture(rig, identity=Identity(session_uuid="sess-1", project_name="Example Project",
                                    working_dir="/Users/x/Org/example/app", title="Nightly report"))
    _register(rig)
    _delete_conversation(rig)
    _again(rig)
    (group,) = _groups(rig.world, "wombatmain")
    assert group["hits"][0]["from_backup"] is True
    assert (group["session"], group["project"], group["working_dir"], group["session_uuid"]) == (
        "Nightly report", "Example Project", "/Users/x/Org/example/app", "sess-1")


def test_a_hit_opens_from_the_vault_bytes_not_a_leftover_file(rig):
    _indexed(rig)
    _capture(rig)
    _register(rig)
    _delete_conversation(rig)
    _again(rig)
    entry = rig.vault.manifests.newest(CONV).main()
    blob, _codec = rig.vault.blobs.find(entry.chunks[0].sha256)
    blob.write_bytes(b"garbage")
    rig.source = BackupTranscripts(lambda: rig.vault)
    fb.register("vault", rig.source)
    answer = _answer(rig.world, "wombatmain")
    assert [g["hits"] for g in answer["groups"]] == [[]] and CONV in answer["stale"]


def test_with_the_vault_off_a_deleted_file_drops_its_rows_exactly_as_step_two(rig):
    _indexed(rig)
    _capture(rig)
    _delete_conversation(rig)
    _again(rig)
    assert _groups(rig.world, "wombatmain") == [] and cq(rig.world, f"SELECT COUNT(*) FROM {K.LIVE_TABLE}") == [(0,)]
    _register(rig)
    vault_lane.reset()
    _again(rig)
    assert [g["conversation_id"] for g in _groups(rig.world, "wombatmain")] == [CONV]


def test_while_the_process_is_booting_a_missing_source_is_not_proof_the_plugin_is_off(rig):
    _indexed(rig)
    _capture(rig)
    fb.begin_boot()
    _delete_conversation(rig)
    _again(rig)
    assert cq(rig.world, f"SELECT COUNT(*) FROM {K.LIVE_TABLE} WHERE base_point_id = 'vault'") == [(4,)]
    _register(rig)
    fb.end_boot()
    _again(rig)
    assert [g["conversation_id"] for g in _groups(rig.world, "wombatmain")] == [CONV]
    fb.unregister("vault")
    _again(rig)
    assert cq(rig.world, f"SELECT COUNT(*) FROM {K.LIVE_TABLE}") == [(0,)]


def test_a_row_the_vault_cannot_serve_is_dropped_not_left_to_lie(rig):
    _indexed(rig)
    _register(rig)
    _delete_conversation(rig)
    _again(rig)
    assert _groups(rig.world, "wombatmain") == [] and cq(rig.world, f"SELECT COUNT(*) FROM {K.LIVE_TABLE}") == [(0,)]


def test_a_vault_copy_older_than_what_was_indexed_is_dropped_and_the_vaults_bytes_are_indexed(rig):
    _indexed(rig)
    _capture(rig)
    main = rig.world["main"]
    main.write_bytes(main.read_bytes() + rec(2, "a later message about zebrathird"))
    scan(rig.world)
    drain(rig.world)
    go_ready(rig.world)
    assert [g["conversation_id"] for g in _groups(rig.world, "zebrathird")] == [CONV]
    _register(rig)
    _delete_conversation(rig)
    _again(rig)
    assert _groups(rig.world, "zebrathird") == []
    (group,) = _groups(rig.world, "wombatmain")
    assert group["conversation_id"] == CONV and all(hit["from_backup"] is True for hit in group["hits"])


def test_a_conversation_gone_before_the_index_existed_is_indexed_from_the_vault_codex_included(rig):
    scan(rig.world)
    _capture(rig, codex=True)
    _register(rig)
    _delete_conversation(rig)
    _again(rig)
    (group,) = _groups(rig.world, "wombatmain")
    assert group["conversation_id"] == CONV and all(hit["from_backup"] is True for hit in group["hits"])
    (codex,) = _groups(rig.world, "okapiprotocol")
    assert codex["conversation_id"] == CODEX_ID and codex["hits"] and all(hit["from_backup"] is True for hit in codex["hits"])
    assert "\x02okapiprotocol\x03" in codex["hits"][0]["snippet"]
    assert cq(rig.world, f"SELECT family FROM {K.LIVE_TABLE} WHERE conversation_id = ?", CODEX_ID) == [("codex",)]
    (sub,) = _groups(rig.world, SUBAGENT_WORDS[2])
    assert sub["hits"][0]["file_kind"] == "subagent"


def test_an_original_that_comes_back_replaces_its_vault_rows_with_a_whole_disk_read(rig):
    _indexed(rig)
    _capture(rig)
    _register(rig)
    _delete_conversation(rig)
    _again(rig)
    rig.world["main"].write_bytes(rec(0, "the restored original says quokkareborn"))
    _again(rig)
    rows = cq(rig.world, f"SELECT path, base_point_id FROM {K.LIVE_TABLE} WHERE file_kind = 'conversation'")
    assert rows == [(str(rig.world["main"]), None)]
    (group,) = _groups(rig.world, "quokkareborn")
    assert all(hit["from_backup"] is False for hit in group["hits"])
    assert _groups(rig.world, "wombatmain") == []


def test_a_copy_of_a_conversation_never_indexes_it_twice(rig):
    _indexed(rig)
    copy = rig.world["corpus"] / "-other-folder" / f"{CONV}.jsonl"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(rig.world["main"].read_bytes())
    scan(rig.world)
    drain(rig.world)
    _capture(rig)
    _register(rig)
    copy.unlink()
    _again(rig)
    paths = [r[0] for r in cq(rig.world, f"SELECT path FROM {K.LIVE_TABLE} WHERE file_kind = 'conversation' AND conversation_id = ?", CONV)]
    assert paths == [str(rig.world["main"])]


def test_an_old_copy_folder_is_retired_with_its_rows_and_the_conversation_comes_back_from_the_vault(rig):
    from src.core.deepsearch.live.indexer import FileSpec, index_file

    gone_id = "99999999-aaaa-bbbb-cccc-999999999999"
    folder = rig.world["state"] / K.BACKUP_COPY_DIR
    folder.mkdir()
    old = folder / f"{gone_id}.abc123def456.jsonl"
    old.write_bytes(rec(0, "the retired lane copied narwhalprotocol"))
    with closing(cache_db.open_cache(rig.world["state"])) as conn:
        index_file(conn, FileSpec(gone_id, str(old), K.FILE_CONVERSATION, "claude"), overrides={}, scope="all")
    assert cq(rig.world, f"SELECT COUNT(*) FROM {K.LIVE_TABLE} WHERE path = ?", str(old)) == [(1,)]
    scan(rig.world)
    drain(rig.world)
    go_ready(rig.world)
    assert cq(rig.world, f"SELECT COUNT(*) FROM {K.LIVE_TABLE} WHERE path = ?", str(old)) == [(0,)]
    assert not folder.exists() and [g["conversation_id"] for g in _groups(rig.world, "narwhalprotocol")] == []

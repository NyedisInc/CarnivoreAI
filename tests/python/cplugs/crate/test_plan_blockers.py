
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.db import connect, db_path_for
from src.cplugs.crate import entries_out, folders
from src.cplugs.crate import forbidden
from src.cplugs.crate import policy as P
from src.cplugs.crate.plan import RecipientInvalid, build_plan
from src.cplugs.sdk import crate_sources as cs
from src.cplugs.sdk.crate_sources import PaneListing
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request, session_request
from tests.python.cplugs.crate.forbidden_world import plant_canaries, plant_symlink
from tests.python.inventory.world import CONV_A, CONV_A0, EPOCH_A, TMUX_A, UUID_A, UUID_B


@pytest.fixture
def world(tmp_path: Path) -> SimpleNamespace:
    return make_world(tmp_path)


def _codes(plan) -> list:
    return [b["code"] for b in plan.blockers]


def _detail(plan, code: str) -> str:
    return " | ".join(b["detail"] for b in plan.blockers if b["code"] == code)


def _transcript(w: SimpleNamespace, conv: str) -> Path:
    return Path(w.home) / "projects" / slugify_project_dir(w.root1) / f"{conv}.jsonl"


def test_inventory_blockers_are_carried_word_for_word(world: SimpleNamespace) -> None:
    journal = Path(world.state) / "session-journal" / "journal.json"
    data = json.loads(journal.read_text())
    data["offer"] = {"sessions": [UUID_A]}
    journal.write_text(json.dumps(data))
    plan = build_plan(env_for(world), project_request(world))
    assert "the open reopen offer names this session; answer the offer first" in _detail(plan, "inventory_blocked")


def test_a_live_session_and_an_unanswered_listing_block(world: SimpleNamespace) -> None:
    live = build_plan(env_for(world, PaneListing(ok=True, panes=((TMUX_A, EPOCH_A, None),))), session_request())
    assert _codes(live) == ["session_live"] and TMUX_A in _detail(live, "session_live")
    down = build_plan(env_for(world, PaneListing(ok=False, reason="no socket")), session_request())
    assert "session_live" in _codes(down)


def test_a_remote_session_blocks(world: SimpleNamespace) -> None:
    with closing(connect(db_path_for(world.state))) as conn:
        conn.execute("UPDATE sessions SET host_key = 'peer-abc' WHERE session_uuid = ?", (UUID_A,))
        conn.commit()
    assert "session_remote" in _codes(build_plan(env_for(world), session_request()))


def test_a_store_with_no_policy_blocks(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(P.POLICY, "claude/todo")
    plan = build_plan(env_for(world), session_request())
    assert _codes(plan) == ["no_crate_policy"] and "claude/todo" in _detail(plan, "no_crate_policy")


def test_a_forbidden_and_a_dataless_source_block(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    plant_canaries(world)
    plant_symlink(world)
    assert "source_forbidden" in _codes(build_plan(env_for(world), session_request()))
    (Path(world.tmp).parent / "w2").mkdir()
    world2 = make_world(Path(world.tmp).parent / "w2")
    target = str(_transcript(world2, CONV_A0))
    monkeypatch.setattr(forbidden.dataless, "is_dataless_file", lambda p: str(p) == target)
    plan = build_plan(env_for(world2), session_request())
    assert _codes(plan) == ["source_dataless"] and target in _detail(plan, "source_dataless")


def test_a_missing_conversation_blocks_and_names_a_legacy_point(world: SimpleNamespace) -> None:
    _transcript(world, CONV_A0).unlink()
    plan = build_plan(env_for(world), session_request())
    assert _codes(plan) == ["conversation_missing"] and CONV_A0 in _detail(plan, "conversation_missing")
    assert "legacy restore point" not in _detail(plan, "conversation_missing")
    _transcript(world, CONV_A).unlink()
    for rollout in Path(world.codex).glob(f"sessions/*/*/*/rollout-*-{CONV_A}.jsonl"):
        rollout.unlink()
    plan = build_plan(env_for(world), session_request())
    assert "a legacy restore point exists" in _detail(plan, "conversation_missing")


def test_an_air_gapped_project_refuses_a_share(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    assert build_plan(env_for(world), project_request(world, "share")).ok
    with closing(connect(db_path_for(world.state))) as conn:
        conn.execute("UPDATE projects SET air_gap = 1 WHERE id = ?", (world.p1,))
        conn.commit()
    assert "share_air_gapped" in _codes(build_plan(env_for(world), project_request(world, "share")))
    assert build_plan(env_for(world), project_request(world)).ok
    monkeypatch.setattr(cs, "project_air_gapped", lambda pid, state_dir: None)
    assert "share_air_gapped" in _codes(build_plan(env_for(world), session_request(variant="share")))


def test_an_unusable_folder_and_no_space_block(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for bad in ("relative/folder", str(tmp_path / "absent")):
        plan = build_plan(env_for(world, folder=bad), session_request())
        assert _codes(plan) == ["folder_unavailable"], bad
    real = tmp_path / "real"
    real.mkdir()
    os.symlink(real, tmp_path / "link")
    assert "symlink" in _detail(build_plan(env_for(world, folder=str(tmp_path / "link")), session_request()), "folder_unavailable")
    monkeypatch.setattr(folders, "free_bytes", lambda path: 0)
    assert _codes(build_plan(env_for(world), session_request())) == ["no_space"]


def test_a_folder_inside_a_synced_root_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synced = tmp_path / "Library" / "Mobile Documents" / "crates"
    synced.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(folders.FolderUnavailable, match="synced folder"):
        folders.check(synced)


def test_encryption_needs_a_valid_recipient(world: SimpleNamespace) -> None:
    plan = build_plan(env_for(world), session_request(encrypt=True))
    assert _codes(plan) == ["no_recipients"]
    with pytest.raises(RecipientInvalid):
        build_plan(env_for(world), session_request(encrypt=True, recipients=("age1notakey",)))
    from src.cplugs.sdk.crate_format import generate
    _identity, recipient = generate()
    assert build_plan(env_for(world), session_request(encrypt=True, recipients=(recipient,))).ok


def test_an_unreadable_claim_blocks(world: SimpleNamespace) -> None:
    with closing(sqlite3.connect(Path(world.state) / "bookmarks.db")) as conn:
        conn.execute("ALTER TABLE bookmarks DROP COLUMN session_row_id")
        conn.commit()
    plan = build_plan(env_for(world), session_request())
    assert "rows_unreadable" in _codes(plan) and "bookmarks" in _detail(plan, "rows_unreadable")


def test_preflight_names_a_query_that_cannot_run(world: SimpleNamespace) -> None:
    good = cs.RowQuery(None, cs.MAIN_STORE, "sessions", "session_uuid = ?", (UUID_A,))
    bad = cs.RowQuery(None, cs.MAIN_STORE, "sessions", "no_such_column = ?", (1,))
    assert cs.preflight([good], state_dir=world.state) == ([], {(cs.MAIN_STORE, "sessions"): 1})
    both = cs.RowQuery(None, cs.MAIN_STORE, "sessions", "id = ?", (world.row_a,))
    assert cs.preflight([good, both], state_dir=world.state)[1] == {(cs.MAIN_STORE, "sessions"): 1}
    [problem], _counts = cs.preflight([good, bad], state_dir=world.state)
    assert "sessions" in problem and "no_such_column" in problem


def test_an_earlier_conversations_file_outside_its_root_blocks(world: SimpleNamespace) -> None:
    outside = Path(world.tmp) / "outside-enc"
    outside.mkdir()
    (outside / f"{CONV_A0}.jsonl").write_text('{"x":1}\n')
    os.symlink(outside, Path(world.home) / "projects" / "-linked-enc")
    plan = build_plan(env_for(world), session_request())
    assert "file_not_traced" in _codes(plan) and "resolves outside" in _detail(plan, "file_not_traced")


def test_an_unreadable_entry_blocks(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entries_out.cs, "load_trust_map", lambda path: None)
    plan = build_plan(env_for(world), project_request(world))
    assert _codes(plan) == ["entry_unreadable"] and "folder trust" in _detail(plan, "entry_unreadable")


def test_a_fork_child_warns_that_its_parent_is_not_carried(world: SimpleNamespace) -> None:
    plan = build_plan(env_for(world), session_request(UUID_B))
    assert plan.ok and any(w.startswith("fork_parent_not_carried") and UUID_A in w for w in plan.warnings)
    assert not any(w.startswith("fork_parent_not_carried") for w in build_plan(env_for(world), project_request(world)).warnings)


def test_the_fingerprint_is_stable_and_moves_when_a_file_grows(world: SimpleNamespace) -> None:
    env = env_for(world)
    first, second = build_plan(env, session_request()), build_plan(env, session_request())
    assert first.fingerprint == second.fingerprint and len(first.fingerprint) == 64
    with open(_transcript(world, CONV_A), "a") as handle:
        handle.write('{"more":1}\n')
    assert build_plan(env, session_request()).fingerprint != first.fingerprint
    assert build_plan(env, session_request(label="x")).fingerprint != first.fingerprint


def test_a_blocked_plan_is_still_answered(world: SimpleNamespace) -> None:
    plan = build_plan(env_for(world, PaneListing(ok=False)), project_request(world))
    assert not plan.ok and plan.conversations and plan.files and plan.fingerprint

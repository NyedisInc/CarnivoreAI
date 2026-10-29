
from __future__ import annotations

import asyncio
import functools
from contextlib import closing
from pathlib import Path
from typing import Any, Dict

import pytest

from test_session_move import CONVERSATION, EVENTS, hooks_for, seed, subject_of, world  # noqa: F401

from src.api import pack_migrate_env as env_mod  # noqa: E402
from src.core.claude_transcript_correlate import slugify_project_dir  # noqa: E402
from src.core.pack.migrate import apply  # noqa: E402
from src.core.pack.machines import restrictions  # noqa: E402
from src.core.pack.migrate.plan import MigrateError  # noqa: E402
from src.core.pack.move import ops, session_move, turn  # noqa: E402
from src.core.pack.send import check as send_check  # noqa: E402

UUID = "sess-0001-aaaa"


def _send(a, b, link, monkeypatch, mode: str, **kw: Any) -> Dict[str, Any]:
    monkeypatch.setattr(turn, "wait_for_turn_end", functools.partial(turn.wait_for_turn_end, settle=0.02, poll=0.005))
    return asyncio.run(session_move.move_session(
        env_mod.source_env(), hooks_for(a, ["working", "idle"], {UUID: "larkspur"}), apply.guarded(link(a, b)), subject=subject_of(a, UUID),
        target_install_id="iid-b", target_label="studio", wait_seconds=5, mode=mode, **kw))


def _row(machine, uuid: str):
    with closing(machine.conn()) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE session_uuid = ?", (uuid,)).fetchone()
        return dict(row) if row else None


def test_copy_forks_on_the_target_and_leaves_the_original_alone(world, monkeypatch) -> None:
    a, b, link = world
    uid, root_a, root_b = seed(a, b, {})
    before = _row(a, UUID)
    done = _send(a, b, link, monkeypatch, "copy")

    assert "a:sleep" not in EVENTS and "a:hide" not in EVENTS, EVENTS
    assert EVENTS.index("a:find:idle") < EVENTS.index("b:launch"), "a copy waits for the turn end like a move"
    after = _row(a, UUID)
    assert after == before and after["lifecycle"] == "running" and after["archived_at"] is None

    assert len(b.launched) == 1
    argv = b.launched[0]["agent_extra_args"]
    assert argv[argv.index("--resume") + 1] == CONVERSATION and argv.count("--fork-session") == 1, argv
    copy_uuid = done["target_session_uuid"]
    assert copy_uuid != UUID and _row(b, copy_uuid)["claude_session_uuid"] == CONVERSATION and _row(b, UUID) is None
    assert (b.claude / slugify_project_dir(str(root_b)) / f"{CONVERSATION}.jsonl").read_text() == (a.claude / slugify_project_dir(str(root_a)) / f"{CONVERSATION}.jsonl").read_text()
    with closing(a.conn()) as conn:
        assert ops.view(conn, done["op_id"])["state"] == "moved" and ops.view(conn, done["op_id"])["detail"]["mode"] == "copy"
        assert ops.forward_for(conn, UUID) is None, "a copy is not a forward: the original lives here"


def test_fresh_starts_a_new_agent_with_no_conversation(world, monkeypatch) -> None:
    a, b, link = world
    seed(a, b, {})
    before = _row(a, UUID)
    done = _send(a, b, link, monkeypatch, "fresh")

    assert "a:sleep" not in EVENTS and "a:find:working" not in EVENTS, "a fresh agent waits for nothing"
    assert _row(a, UUID) == before
    assert len(b.launched) == 1 and "--resume" not in (b.launched[0].get("agent_extra_args") or []) and "--fork-session" not in (b.launched[0].get("agent_extra_args") or [])
    assert not list((b.claude / slugify_project_dir(str(b.projects / "trader"))).glob("*.jsonl")), "no conversation file is carried"
    new = _row(b, done["target_session_uuid"])
    assert new is not None and new["claude_session_uuid"] is None and new["title"] == before["title"]


def test_with_project_adds_the_project_before_the_mode_and_without_it_the_refusal_stays(world, monkeypatch) -> None:
    a, b, link = world
    uid, root_a, root_b = seed(a, b, {})
    with closing(b.conn()) as conn:
        conn.execute("DELETE FROM projects WHERE uid = ?", (uid,))
        conn.commit()
    with pytest.raises(MigrateError) as refused:
        _send(a, b, link, monkeypatch, "copy")
    assert refused.value.code == "project_not_on_target" and b.launched == []

    async def add_project() -> None:
        EVENTS.append("a:add_project")
        from src.core.project_writes import create_project
        with closing(b.conn()) as conn:
            made = create_project(conn, name="trader", path=str(root_b))
            conn.execute("UPDATE projects SET uid = ?, pack_state = 'replica', home_install_id = 'iid-a' WHERE id = ?", (uid, made["id"]))
            conn.commit()

    EVENTS.clear()
    _send(a, b, link, monkeypatch, "copy", add_project=add_project)
    assert EVENTS.index("a:find:idle") < EVENTS.index("a:add_project") < EVENTS.index("b:launch"), "the replica is added after the turn wait, never before it"


def test_a_second_copy_of_a_held_conversation_is_refused_cleanly_before_any_wait(world, monkeypatch) -> None:
    a, b, link = world
    seed(a, b, {})
    _send(a, b, link, monkeypatch, "copy")
    EVENTS.clear()
    with pytest.raises(MigrateError) as refused:
        _send(a, b, link, monkeypatch, "copy")
    assert refused.value.code == "conversation_already_here" and refused.value.step == "check", refused.value.code
    assert "a:find:idle" not in EVENTS and len(b.launched) == 1, "refused before the turn wait, the upload and any launch"
    with closing(b.conn()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE claude_session_uuid = ?", (CONVERSATION,)).fetchone()[0] == 1


@pytest.mark.parametrize("mode", ["copy", "fresh"])
def test_copy_and_fresh_respect_a_target_that_hosts_no_agents(world, monkeypatch, mode) -> None:
    a, b, link = world
    seed(a, b, {})
    b.restrictions = restrictions.Restrictions(may_host_agents=False)
    with pytest.raises(MigrateError) as refused:
        _send(a, b, link, monkeypatch, mode)
    assert refused.value.code == "pack_restricted" and "may_host_agents" in str(refused.value.detail) and b.launched == []
    ready = asyncio.run(send_check.check(env_mod.source_env(), apply.guarded(link(a, b)), subject=subject_of(a, UUID), account_key="larkspur"))
    assert ready["copy"]["reason"] == "pack_restricted" and ready["fresh"]["reason"] == "pack_restricted" and ready["move"]["ok"]


def test_check_reports_each_mode_and_changes_nothing(world) -> None:
    a, b, link = world
    uid, root_a, root_b = seed(a, b, {})

    def snapshot():
        out = []
        for m in (a, b):
            with closing(m.conn()) as conn:
                out.append((conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], conn.execute("SELECT COUNT(*) FROM pack_session_moves").fetchone()[0]))
        return out

    before = snapshot()
    ready = asyncio.run(send_check.check(env_mod.source_env(), apply.guarded(link(a, b)), subject=subject_of(a, UUID), account_key="larkspur"))
    assert ready["move"]["ok"] and ready["copy"]["ok"] and ready["fresh"]["ok"] and ready["project_on_target"] is True
    with closing(b.conn()) as conn:
        conn.execute("DELETE FROM projects WHERE uid = ?", (uid,))
        conn.commit()
    gone = asyncio.run(send_check.check(env_mod.source_env(), apply.guarded(link(a, b)), subject=subject_of(a, UUID), account_key="larkspur"))
    assert gone["project_on_target"] is False and gone["project_addable"]["ok"] is True
    assert all(gone[m] == {"ok": False, "reason": "project_not_on_target"} for m in ("move", "copy", "fresh"))
    assert snapshot() == before, "a check writes no session row and no op row on either computer"


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_an_asleep_session_is_sent_without_a_turn_wait_or_a_sleep(world, monkeypatch, mode) -> None:
    a, b, link = world
    seed(a, b, {})
    with closing(a.conn()) as conn:
        conn.execute("UPDATE sessions SET lifecycle = 'stopped', lifecycle_source = 'slept_by_user' WHERE session_uuid = ?", (UUID,))
        conn.commit()
    done = _send(a, b, link, monkeypatch, mode)

    assert not [e for e in EVENTS if e.startswith("a:find") or e == "a:sleep"], EVENTS
    assert len(b.launched) == 1 and done["session_uuid"] == UUID


def test_check_reports_the_about_size_of_what_a_send_carries(world, tmp_path) -> None:
    import subprocess
    from src.core.pack.carry import scan

    a, b, link = world
    seed(a, b, {})
    ready = asyncio.run(send_check.check(env_mod.source_env(), apply.guarded(link(a, b)), subject=subject_of(a, UUID), account_key="larkspur"))
    assert isinstance(ready["carry"]["total_bytes"], int)
    root = tmp_path / "proj"
    root.mkdir()
    (root / "loose.bin").write_bytes(b"x" * 1000)
    assert scan.scan_project(str(root)).total_bytes() == 1000
    repo = root / "repo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "m"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True, capture_output=True)
    assert scan.scan_project(str(root)).total_bytes() > 1000

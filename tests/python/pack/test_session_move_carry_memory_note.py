
from __future__ import annotations

import asyncio
import functools
from contextlib import closing
from pathlib import Path

import pytest

from test_session_move import CONVERSATION, hooks_for, seed, subject_of, world  # noqa: F401

from src.api import pack_migrate_env as env_mod  # noqa: E402
from src.core.claude_transcript_correlate import slugify_project_dir  # noqa: E402
from src.core.pack.migrate import apply, transcripts  # noqa: E402
from src.core.pack.move import interrupt, moved_note, session_move, turn  # noqa: E402

UUID = "sess-0001-aaaa"


def test_memory_rides_the_first_move_only_and_the_longer_copy_wins(world, monkeypatch, tmp_path: Path) -> None:
    a, b, link = world
    uid, root_a, root_b = seed(a, b, {})
    folder = a.claude / slugify_project_dir(str(root_a))
    (folder / "memory").mkdir()
    (folder / "memory" / "MEMORY.md").write_text("- [a](a.md)\n")
    relay = tmp_path / "relay-projects" / slugify_project_dir(str(root_a))
    relay.mkdir(parents=True)
    default_copy = (folder / f"{CONVERSATION}.jsonl").read_bytes()
    (relay / f"{CONVERSATION}.jsonl").write_bytes(default_copy + b'{"n":"later"}\n')
    monkeypatch.setattr(transcripts, "transcript_roots", lambda: (a.claude, tmp_path / "relay-projects"))

    ahead = session_move.conversation_files(str(root_a), CONVERSATION)[0]
    assert ahead["path"].startswith(str(tmp_path / "relay-projects")) and ahead["size"] > len(default_copy)
    plain = [f["rel"] for f in session_move.conversation_files(str(root_a), CONVERSATION)]
    assert plain == [f"{CONVERSATION}.jsonl"]
    got = {f["rel"]: f for f in session_move.conversation_files(str(root_a), CONVERSATION, with_memory=True, prefer_root=tmp_path / "relay-projects")}
    assert "memory/MEMORY.md" in got
    assert got[f"{CONVERSATION}.jsonl"]["path"].startswith(str(tmp_path / "relay-projects"))
    (folder / f"{CONVERSATION}.jsonl").write_bytes(b'{"n":"other"}\n')
    assert session_move.conversation_files(str(root_a), CONVERSATION, prefer_root=tmp_path / "relay-projects")[0]["path"].startswith(str(tmp_path / "relay-projects"))

    with closing(a.conn()) as conn:
        pid = conn.execute("SELECT project_id FROM sessions WHERE session_uuid = ?", (UUID,)).fetchone()[0]
        assert moved_note.first_to_target(conn, pid, "iid-b", "op-new") is True
        conn.execute("INSERT INTO pack_session_moves (id, role, session_uuid, source_install_id, target_install_id, state, step, detail_json, started_at) "
                     "VALUES ('op-old', 'source', ?, 'iid-a', 'iid-b', 'moved', 'forward', '{}', 't')", (UUID,))
        conn.commit()
        assert moved_note.first_to_target(conn, pid, "iid-b", "op-new") is False
        assert moved_note.first_to_target(conn, pid, "iid-c", "op-new") is True


def test_a_resting_agent_gets_the_note_file_and_no_paste(world, monkeypatch) -> None:
    a, b, link = world
    uid, root_a, root_b = seed(a, b, {})
    folder = a.claude / slugify_project_dir(str(root_a))
    (folder / "memory").mkdir()
    (folder / "memory" / "MEMORY.md").write_text("- [a](a.md)\n")
    monkeypatch.setattr(turn, "wait_for_turn_end", functools.partial(turn.wait_for_turn_end, settle=0.02, poll=0.005))
    pasted = []

    async def tell(*args, **kw):
        pasted.append(1)
        return {}

    monkeypatch.setattr(interrupt, "tell_continue", tell)
    asyncio.run(session_move.move_session(env_mod.source_env(), hooks_for(a, ["idle"], {UUID: "larkspur"}), apply.guarded(link(a, b)), subject=subject_of(a, UUID),
                                          target_install_id="iid-b", target_label="studio", wait_seconds=5))
    landed = b.claude / slugify_project_dir(str(root_b)) / "memory"
    note = next(landed.glob("moved-*.md")).read_text()
    assert pasted == [] and "moved to studio" in note and str(root_b) in note and chr(0x2014) not in note and chr(0x2013) not in note
    assert "(moved-" in (landed / "MEMORY.md").read_text() and (landed / "MEMORY.md").read_text().startswith("- [a](a.md)\n")

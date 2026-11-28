
from __future__ import annotations

import json
import os
import tarfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.agy import identity, transcripts
from src.core.deepsearch import rules as ds_rules
from src.core.deepsearch.extract import extract
from src.core.pack.globalsync import apply as gs_apply, collect
from src.core.pack.migrate import transcripts as claude_transcripts
from src.core.pack.move import agy_files
from src.core.pack.migrate.receive import MigrateRefused
from src.core.session_transcript_presence import (
    CONVERSATION_ABSENT, CONVERSATION_PRESENT, CONVERSATION_UNCHECKED, family_conversation_presence)

CID = "08b90c11-a1f0-4a67-bfd0-73c99ec89157"
LINES = [
    {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-11-21T22:08:00Z", "content": "fix the build"},
    {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "created_at": "2026-11-21T22:08:05Z", "content": "looking now"},
    {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "thinking": "hmm", "tool_calls": [{"name": "run_command", "args": {"command": "ls"}}]},
    {"step_index": 3, "source": "MODEL", "type": "GENERIC", "content": "tool output"},
    {"step_index": 4, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "content": "sys"},
]


def make_agy_home(tmp: Path, cid: str = CID) -> Path:
    home = tmp / "agyhome"
    logs = home / "brain" / cid / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    text = "\n".join(json.dumps(x) for x in LINES) + "\nnot json\n[1,2]\n"
    (logs / "transcript.jsonl").write_text(text)
    (logs / "transcript_full.jsonl").write_text(text)
    (home / "brain" / cid / "plan.md").write_text("artifact")
    (home / "conversations").mkdir()
    (home / "conversations" / f"{cid}.db").write_bytes(b"SQLite format 3\0store")
    (home / "settings.json").write_text('{"secret": "no"}')
    (home / "history.jsonl").write_text("{}")
    return home


def test_reader_discovery_and_carry_set(tmp_path):
    home = make_agy_home(tmp_path)
    found = list(transcripts.iter_conversations(home))
    assert [c["id"] for c in found] == [CID]
    msgs = transcripts.read_messages(Path(found[0]["path"]))
    assert [(m["role"], m["text"]) for m in msgs] == [("user", "fix the build"), ("assistant", "looking now")]
    assert transcripts.read_messages(Path(found[0]["path"]), limit=1)[0]["role"] == "assistant"
    assert transcripts.read_messages(tmp_path / "missing.jsonl") == []
    assert not transcripts.valid_id("../x") and transcripts.brain_dir("../x", home) is None
    (home / "brain" / CID / "link").symlink_to(home / "settings.json")
    rels = {f["rel"] for f in transcripts.carry_files(CID, home)}
    assert f"conversations/{CID}.db" in rels and f"brain/{CID}/plan.md" in rels
    assert not any("link" in r or "settings" in r or "history" in r for r in rels)


def test_presence_is_measured_for_agy_and_not_for_other_custom(tmp_path):
    home = make_agy_home(tmp_path)
    present = family_conversation_presence("custom", CID, agent_is_agy=True, agy_home=str(home))
    assert present.outcome == CONVERSATION_PRESENT and present.path.name == "transcript.jsonl"
    other = "11111111-2222-4333-8444-555555555555"
    assert family_conversation_presence("custom", other, agent_is_agy=True, agy_home=str(home)).outcome == CONVERSATION_ABSENT
    assert family_conversation_presence("agy", CID, agy_home=str(home)).outcome == CONVERSATION_PRESENT
    assert family_conversation_presence("custom", other, agy_home=str(home)).outcome == CONVERSATION_UNCHECKED
    assert family_conversation_presence("agy", None, agy_home=str(home)).outcome == CONVERSATION_UNCHECKED
    assert family_conversation_presence("agy", CID, agy_home=str(tmp_path / "nowhere")).outcome == CONVERSATION_UNCHECKED


def test_identity_is_by_agent_block_never_by_name():
    agy = SimpleNamespace(id="work", agent=SimpleNamespace(process="agy", rules="agy"))
    named = SimpleNamespace(id="agy", agent=SimpleNamespace(process="other", rules=None))
    assert identity.is_agy_profile(agy) and not identity.is_agy_profile(named)
    assert identity.row_is_agy({"agent_family": "custom", "agent_type": "WORK"}, [agy, named])
    assert not identity.row_is_agy({"agent_family": "custom", "agent_type": "agy"}, [agy, named])
    assert not identity.row_is_agy({"agent_family": "claude", "agent_type": "work"}, [agy])


def test_deep_search_reads_agy_lines_and_accepts_the_family():
    rules = ds_rules.effective(None, "agy")
    got = [extract(json.dumps(x).encode(), rules, "agy") for x in LINES]
    assert got[0] == ("user", "fix the build") and got[1][0] == "assistant"
    assert got[2] is None and got[3] is None and got[4] is None
    keep = ds_rules.effective({"blocks": {"tool_use": "keep"}}, "agy")
    kept = extract(json.dumps(LINES[2]).encode(), keep, "agy")
    assert kept[0] == "tool" and "run_command" in kept[1]
    assert extract(b"nope", rules, "agy") is None
    assert ds_rules.version_of({"families": {"agy": {"max_message_chars": 100}}}, "agy") != ds_rules.version_of(None, "agy")


def test_manifest_walk_lists_agy_conversations(tmp_path, monkeypatch):
    from src.core.transcript_manifest import refresh

    home = make_agy_home(tmp_path)
    monkeypatch.setattr(transcripts, "AGY_HOME", home)
    walk = refresh.walk(claude_roots=[tmp_path / "none"])
    rows = [o for o in walk.observed if o.family == "agy"]
    assert [(o.conversation_id, o.kind) for o in rows] == [(CID, "conversation")]
    assert rows[0].source_path == f"brain/{CID}/.system_generated/logs/transcript.jsonl"
    assert str(home / "brain") in [str(Path(r)) for r in walk.complete_roots] or any(r.endswith("brain") for r in walk.complete_roots)


def _profiles():
    return [SimpleNamespace(id="agy-main", agent=SimpleNamespace(process="agy", rules="agy", resume="agy --conversation {id}"))]


def test_move_plan_for_an_agy_row(tmp_path, monkeypatch):
    from src.core.session_move.plan import build_plan, read_row
    from tests.session_move.helpers import FakeSettings, add_project, add_session, migrated_state, open_conn, resumable

    home = make_agy_home(tmp_path)
    monkeypatch.setattr(transcripts, "AGY_HOME", home)
    real = identity.row_is_agy
    monkeypatch.setattr(identity, "row_is_agy", lambda row, profiles=None: real(row, _profiles()))
    temp_root = tmp_path / "carnivore-projects"
    source = temp_root / "ses_ab12"
    source.mkdir(parents=True)
    (source / "notes.md").write_text("x")
    project = temp_root / "app"
    project.mkdir()
    state = migrated_state(tmp_path)

    def plan_for(conversation: str):
        with closing(open_conn(state)) as conn:
            pid = add_project(conn, project, "app") if conversation == CID else 1
            uuid = add_session(conn, source, conversation=conversation, name=f"agy_{conversation[:4]}")
            conn.execute("UPDATE sessions SET agent_family='custom', agent_type='agy-main' WHERE session_uuid=?", (uuid,))
            conn.commit()
            return build_plan(conn, read_row(conn, uuid), project_id=pid, new_folder=None, settings=FakeSettings(working_dir=temp_root, state_dir=state),
                              preview=resumable(), home=str(tmp_path / "home"))

    assert plan_for(CID).ok
    missing = plan_for("11111111-2222-4333-8444-555555555555")
    assert not missing.ok and any("transcript is not on this computer" in str(r) for r in missing.refusals)


def test_agy_conversation_is_carried_and_filed_safely(tmp_path):
    src_home = make_agy_home(tmp_path)
    files = agy_files.source_files(CID, src_home)
    assert {f["rel"] for f in files} >= {f"conversations/{CID}.db", f"brain/{CID}/plan.md"}
    archive = tmp_path / "s.tgz"
    claude_transcripts.build_archive(files, str(archive))
    wire = [{"rel": f["rel"], "sha256": f["sha256"]} for f in files]
    target = tmp_path / "target"
    target.mkdir()
    agy_files.file_conversation(str(archive), wire, CID, target)
    assert (target / "conversations" / f"{CID}.db").read_bytes() == (src_home / "conversations" / f"{CID}.db").read_bytes()
    assert not (target / "settings.json").exists()
    agy_files.file_conversation(str(archive), wire, CID, target)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(MigrateRefused) as bad:
        agy_files.file_conversation(str(archive), wire, "11111111-2222-4333-8444-555555555555", other)
    assert bad.value.code == "unsafe_archive" and not any(other.iterdir())
    evil = tmp_path / "evil.tgz"
    (tmp_path / "x").write_text("x")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(tmp_path / "x", arcname="settings.json")
    with pytest.raises(MigrateRefused):
        agy_files.file_conversation(str(evil), [{"rel": "settings.json", "sha256": "0"}], CID, other)
    linked = tmp_path / "linked"
    (linked).mkdir()
    (linked / "brain").symlink_to(other)
    with pytest.raises(MigrateRefused):
        agy_files.file_conversation(str(archive), wire, CID, linked)
    (src_home / "conversations" / f"{CID}.db").unlink()
    from src.core.pack.migrate.plan import MigrateError

    with pytest.raises(MigrateError) as gone:
        agy_files.source_files(CID, src_home)
    assert gone.value.code == "no_conversation_file"


def test_global_sync_agy_slot_round_trip(tmp_path):
    main = tmp_path / "main"
    config = main / ".gemini" / "config"
    (config / "skills" / "demo").mkdir(parents=True)
    (config / "skills" / "demo" / "SKILL.md").write_text(f"see {main}/x\n")
    (config / "rules").mkdir()
    (config / "rules" / "r.md").write_text("rule")
    (config / "config.json").write_text('{"token": "no"}')
    (config / "mcp_config.json").write_text('{"mcpServers": {"s": {"env": {"T": "no"}}}}')
    slots = collect.slots_for(main, [], ["agy"])
    assert [s.id for s in slots] == ["agy.default"]
    built = collect.build(slots, tmp_path / "b.tgz", main)
    with tarfile.open(built.path) as tar:
        got = sorted(m.name for m in tar if m.isreg())
    assert got == ["agy.default/rules/r.md", "agy.default/skills/demo/SKILL.md"]
    member = tmp_path / "member"
    (member / ".gemini" / "config").mkdir(parents=True)
    args = dict(home=member, accounts_root=member / "a", accounts=[], state=gs_apply.State(tmp_path / "s.json"), backups=tmp_path / "bk", stage_root=tmp_path)
    report = gs_apply.apply_bundle(built.path, **args)
    assert report.written == 2
    assert (member / ".gemini" / "config" / "skills" / "demo" / "SKILL.md").read_text() == f"see {member}/x\n"
    assert not (member / ".gemini" / "config" / "config.json").exists()
    off = gs_apply.apply_bundle(built.path, **{**args, "state": gs_apply.State(tmp_path / "s2.json")}, harnesses=["claude"])
    assert off.written == 0

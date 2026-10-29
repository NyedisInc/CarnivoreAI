
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.core import conversation_writers as cw
from src.core.attention import registry_index
from src.core.claude_config import profile_roots
from src.core.claude_transcript_correlate import (
    CORRELATE_MATCHED,
    correlate_adopted_session,
    default_projects_dir,
    slugify_project_dir,
)
from src.core.project_history.transcripts import transcript_uuid_index
from src.core.session_transcript_presence import CONVERSATION_ABSENT, conversation_presence
from src.core.scheduled_tasks import ScheduledTaskReader

UUID = "44444444-aaaa-bbbb-cccc-000000000004"
WORKING_DIR = "/tmp/managed-work"
EPOCH = 1_800_000_000


@pytest.fixture()
def install(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    (home / ".claude" / "sessions").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(registry_index, "default_registry_directory",
                        lambda: str(home / ".claude" / "sessions"))
    profile = tmp_path / "accounts" / "work"
    (profile / "projects").mkdir(parents=True)
    (profile / "sessions").mkdir(parents=True)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"provider_accounts": {"accounts": [
        {"id": "work", "name": "work", "provider": "claude",
         "claude_config_dir": str(profile)}]}}))
    monkeypatch.setattr(profile_roots, "_default_config_path", lambda: config)
    profile_roots.reset_profile_roots_cache_for_tests()
    yield profile
    profile_roots.reset_profile_roots_cache_for_tests()


def test_the_adopt_correlate_finds_a_transcript_born_in_a_managed_profile(install):
    folder = install / "projects" / slugify_project_dir(WORKING_DIR)
    folder.mkdir()
    (folder / f"{UUID}.jsonl").write_text(json.dumps({
        "type": "user", "isSidechain": False, "timestamp": "2027-01-15T10:00:05Z",
        "sessionId": UUID, "entrypoint": "cli",
        "uuid": "11111111-1111-1111-1111-111111111111",
        "message": {"role": "user", "content": "hello"}}) + "\n")
    assert default_projects_dir() == Path.home() / ".claude" / "projects"
    result = correlate_adopted_session(working_dir=WORKING_DIR, tmux_created_epoch=EPOCH)
    assert result.outcome == CORRELATE_MATCHED
    assert result.claude_session_uuid == UUID


def test_the_reopen_offers_pid_record_and_transcript_are_found(install):
    pid = os.getpid()
    (install / "sessions" / f"{pid}.json").write_text(json.dumps({"pid": pid, "sessionId": UUID}))
    assert cw.read_pid_record(pid)["sessionId"] == UUID
    folder = install / "projects" / "-tmp-x"
    folder.mkdir()
    (folder / f"{UUID}.jsonl").write_text("{}\n")
    assert cw.transcript_paths(UUID) == [str(folder / f"{UUID}.jsonl")]
    assert cw.transcript_paths("55555555-aaaa-bbbb-cccc-000000000005") == []


def test_candidate_project_dirs_include_a_managed_profile(install):
    from src.core.claude_project_dirs import candidate_project_dirs

    folder = install / "projects" / slugify_project_dir(WORKING_DIR)
    folder.mkdir()
    assert candidate_project_dirs(WORKING_DIR) == [folder]


def test_the_resume_preflight_does_not_union_profiles(install):
    folder = install / "projects" / "-tmp-x"
    folder.mkdir()
    (folder / f"{UUID}.jsonl").write_text("{}\n")
    assert conversation_presence(UUID).outcome == CONVERSATION_ABSENT


def test_project_history_resume_index_sees_a_managed_profile_transcript(install):
    folder = install / "projects" / "-tmp-x"
    folder.mkdir()
    (folder / f"{UUID}.jsonl").write_text("{}\n")
    assert UUID in transcript_uuid_index()


def test_scheduled_task_runs_are_counted_from_a_managed_profile(install, tmp_path):
    tasks = tmp_path / "scheduled-tasks"
    (tasks / "nightly").mkdir(parents=True)
    (tasks / "nightly" / "SKILL.md").write_text("---\nname: nightly\n---\nbody\n")
    folder = install / "projects" / "-tmp-sched"
    folder.mkdir()
    enqueue = {"type": "queue-operation", "operation": "enqueue",
               "timestamp": "2026-09-20T21:00:03.000Z", "sessionId": UUID,
               "content": '<scheduled-task name="nightly" file="/x/scheduled-tasks/nightly/SKILL.md">\n'}
    (folder / f"{UUID}.jsonl").write_text(json.dumps(enqueue) + "\n")
    listed = ScheduledTaskReader(tasks_dir=tasks).read()
    assert listed.tasks[0].runs_recorded == 1


def test_nothing_outside_sessions_and_projects_is_read(install):
    (install / ".credentials.json").write_text('{"sessionId": "%s"}' % UUID)
    (install / "auth").mkdir()
    (install / "auth" / f"{UUID}.jsonl").write_text("{}\n")
    (install / f"{UUID}.jsonl").write_text("{}\n")
    assert cw.transcript_paths(UUID) == []
    assert UUID not in transcript_uuid_index()
    assert cw.read_pid_record(os.getpid()) is None
    for root in (*profile_roots.claude_registry_roots(), *profile_roots.profile_subdir_roots(
            default_projects_dir(), "projects")):
        assert root.name in {"sessions", "projects"}

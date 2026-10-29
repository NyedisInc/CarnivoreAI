
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_idleseed_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_idleseed_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.attention.codex_reader import CodexEvidence, CodexTranscriptFacts
from src.core.attention.registry_read import REG_ABSENT, RegistryRecord
from src.core.auto_sleep.idle_seed import (
    SOURCE_CLAUDE_REGISTRY,
    SOURCE_CLAUDE_TRANSCRIPT,
    SOURCE_CODEX_ROLLOUT,
    SOURCE_CODEX_STATUS,
)
from src.core.auto_sleep.idle_seed_paths import (
    resolve_claude_seed,
    resolve_codex_seed,
    stat_mtime,
)

REG_OK_VERDICT = "ok"


def _absent_record() -> RegistryRecord:
    return RegistryRecord(
        verdict=REG_ABSENT, status=None, waiting_for=None, pid=None, session_uuid=None,
        tmux_name=None, cwd=None, status_updated_at=None, started_at=None, version=None,
        detail="no record",
    )


def _ok_record(pid: int) -> RegistryRecord:
    return RegistryRecord(
        verdict=REG_OK_VERDICT, status="idle", waiting_for=None, pid=pid, session_uuid=None,
        tmux_name="cloude_a", cwd=None, status_updated_at=None,
        started_at=datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc), version=None, detail="",
    )




def test_stat_mtime_reads_a_real_file(tmp_path):
    target = tmp_path / "f.json"
    target.write_text("{}")
    got = stat_mtime(str(target))
    assert got is not None and got.tzinfo is not None


def test_stat_mtime_answers_none_for_a_missing_path(tmp_path):
    assert stat_mtime(str(tmp_path / "nope.json")) is None
    assert stat_mtime(None) is None




def test_default_directory_registry_hit_reads_that_files_mtime(tmp_path, monkeypatch):
    registry_dir = tmp_path / "sessions"
    registry_dir.mkdir()
    registry_file = registry_dir / "4242.json"
    registry_file.write_text(json.dumps({"pid": 4242, "status": "idle"}))
    monkeypatch.setattr(
        "src.core.attention.registry_read.default_registry_directory",
        lambda: str(registry_dir),
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({}))

    candidates, floor = resolve_claude_seed(
        registry=_ok_record(4242), cwd=None, claude_session_uuid=None,
        tmux_name="cloude_a", session_started_epoch=None, config_path=config_path,
    )

    sources = {source for _when, source in candidates}
    assert SOURCE_CLAUDE_REGISTRY in sources
    registry_when = next(when for when, source in candidates if source == SOURCE_CLAUDE_REGISTRY)
    assert registry_when is not None
    assert floor == datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)


def test_no_default_hit_falls_back_to_a_managed_profile_directory(tmp_path, monkeypatch):
    default_dir = tmp_path / "default_sessions"
    default_dir.mkdir()
    monkeypatch.setattr(
        "src.core.attention.registry_read.default_registry_directory",
        lambda: str(default_dir),
    )

    profile_dir = tmp_path / "carnivore_work"
    (profile_dir / "sessions").mkdir(parents=True)
    live_pid = os.getpid()
    (profile_dir / "sessions" / f"{live_pid}.json").write_text(
        json.dumps({"pid": live_pid, "status": "idle", "tmux": "cloude_a:@1.%1"})
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "provider_accounts": {"accounts": [
            {"id": "work", "name": "Work", "provider": "claude",
             "claude_config_dir": str(profile_dir)},
        ]},
    }))

    candidates, _floor = resolve_claude_seed(
        registry=_absent_record(), cwd=None, claude_session_uuid=None,
        tmux_name="cloude_a", session_started_epoch=None, config_path=config_path,
    )

    registry_when = next(when for when, source in candidates if source == SOURCE_CLAUDE_REGISTRY)
    assert registry_when is not None


def test_no_hit_anywhere_reads_no_registry_candidate(tmp_path, monkeypatch):
    default_dir = tmp_path / "default_sessions"
    default_dir.mkdir()
    monkeypatch.setattr(
        "src.core.attention.registry_read.default_registry_directory",
        lambda: str(default_dir),
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({}))

    candidates, floor = resolve_claude_seed(
        registry=_absent_record(), cwd=None, claude_session_uuid=None,
        tmux_name="cloude_a", session_started_epoch=1758800000, config_path=config_path,
    )

    assert not any(source == SOURCE_CLAUDE_REGISTRY for _when, source in candidates)
    assert floor == datetime.fromtimestamp(1758800000, tz=timezone.utc)


def test_transcript_candidate_is_present_whenever_a_uuid_is_known(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.core.attention.registry_read.default_registry_directory",
        lambda: str(tmp_path / "empty"),
    )
    (tmp_path / "empty").mkdir()
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({}))

    candidates, _floor = resolve_claude_seed(
        registry=_absent_record(), cwd="/nonexistent/project", claude_session_uuid="not-a-real-uuid",
        tmux_name="cloude_a", session_started_epoch=None, config_path=config_path,
    )

    sources = {source for _when, source in candidates}
    assert SOURCE_CLAUDE_TRANSCRIPT in sources




def test_codex_seed_reads_the_readers_own_status_time_and_the_rollout_mtime(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex_home"
    rollout_dir = codex_home / "sessions"
    rollout_dir.mkdir(parents=True)
    rollout_path = rollout_dir / "rollout-thread-1.jsonl"
    rollout_path.write_text("{}\n")
    monkeypatch.setattr(
        "src.core.auto_sleep.idle_seed_paths.rollout_path_for",
        lambda home, uuid: str(rollout_path),
    )
    status_time = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)
    codex = CodexEvidence(transcript=CodexTranscriptFacts(last_append_at=status_time))

    candidates, floor = resolve_codex_seed(
        codex=codex, codex_session_uuid="thread-1", session_started_epoch=1758800000,
        codex_home=str(codex_home),
    )

    sources = {source: when for when, source in candidates}
    assert sources[SOURCE_CODEX_STATUS] == status_time
    assert sources[SOURCE_CODEX_ROLLOUT] is not None
    assert floor == datetime.fromtimestamp(1758800000, tz=timezone.utc)


def test_codex_seed_with_no_evidence_and_no_uuid_reads_nothing(tmp_path):
    candidates, floor = resolve_codex_seed(
        codex=None, codex_session_uuid=None, session_started_epoch=None,
        codex_home=str(tmp_path),
    )
    assert all(when is None for when, _source in candidates)
    assert floor is None

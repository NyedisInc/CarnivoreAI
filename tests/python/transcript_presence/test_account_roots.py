
from __future__ import annotations

from pathlib import Path

import pytest

from src.core import session_transcript_presence as presence
from src.core.claude_config import transcript_roots

UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    default = tmp_path / "default" / "projects"
    profile = tmp_path / "acct" / "projects"
    (default / "-proj").mkdir(parents=True)
    (profile / "-proj").mkdir(parents=True)
    monkeypatch.setattr(transcript_roots, "claude_transcript_roots", lambda config_path=None: (default, profile))
    return default, profile


def test_a_conversation_in_a_profile_root_is_present(roots) -> None:
    _, profile = roots
    held = profile / "-proj" / f"{UUID}.jsonl"
    held.write_text("{}\n")
    result = presence._measure_presence(UUID, working_dir=None)
    assert result.outcome == presence.CONVERSATION_PRESENT
    assert result.path == held


def test_absent_from_every_root_is_absent(roots) -> None:
    result = presence._measure_presence(UUID, working_dir=None)
    assert result.outcome == presence.CONVERSATION_ABSENT


def test_an_explicit_corpus_root_is_the_only_one_searched(roots, tmp_path: Path) -> None:
    _, profile = roots
    (profile / "-proj" / f"{UUID}.jsonl").write_text("{}\n")
    only = tmp_path / "other"
    only.mkdir()
    result = presence._measure_presence(UUID, corpus_root=only)
    assert result.outcome == presence.CONVERSATION_ABSENT


from __future__ import annotations

from pathlib import Path

import pytest

from src.core import session_sleep
from src.core.session_pane_death import LIFECYCLE_SOURCE_PANE_DEAD

CONV = "7c1d2e3f-aaaa-4bbb-8ccc-0123456789ab"


def _row(**extra) -> dict:
    return {"lifecycle": "stopped", "lifecycle_source": LIFECYCLE_SOURCE_PANE_DEAD, "claude_session_uuid": CONV,
            "archived_at": None, "tmux_created_epoch": 1, "working_dir": "/nowhere/p23", **extra}


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "projects"
    (root / "-nowhere-p23").mkdir(parents=True)
    monkeypatch.setattr("src.core.claude_config.transcript_roots.claude_transcript_roots", lambda *a, **k: (root,))
    monkeypatch.setattr("src.core.session_transcript_presence._cache", {})
    return root


def test_no_transcript_means_closed(corpus):
    assert not session_sleep.is_asleep(_row())
    assert session_sleep.is_closed(_row())


def test_a_transcript_means_asleep(corpus):
    (corpus / "-nowhere-p23" / f"{CONV}.jsonl").write_text("{}\n")
    assert session_sleep.is_asleep(_row())
    assert not session_sleep.is_closed(_row())

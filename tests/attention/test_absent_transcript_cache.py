
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import listing_attention
from src.core.attention.absent_transcript_cache import ABSENT_TRANSCRIPTS
from src.core.attention.transcript_facts import FACTS_UNREADABLE
from src.core.claude_config import profile_roots, transcript_roots
from src.core import claude_transcript_correlate

UUID = "44444444-1a7b-42f9-baba-abacc8720544"
WORKDIR = "/Users/x/proj"
SLUG = "-Users-x-proj"
T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _record(status="idle", updated=T0):
    return SimpleNamespace(known=True, verdict="ok", status=status, status_updated_at=updated)


@pytest.fixture(autouse=True)
def corpus(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    for i in range(40):
        (root / f"-other-{i}").mkdir(parents=True)
    (root / SLUG).mkdir()
    monkeypatch.setattr(claude_transcript_correlate, "default_projects_dir", lambda: root)
    profile_roots.reset_profile_roots_cache_for_tests()
    ABSENT_TRANSCRIPTS.clear()
    scans = []
    real = Path.iterdir

    def counting(self):
        if str(self).startswith(str(tmp_path)):
            scans.append(self)
        return real(self)

    monkeypatch.setattr(Path, "iterdir", counting)
    yield SimpleNamespace(root=root, scans=scans, tmp=tmp_path)
    ABSENT_TRANSCRIPTS.clear()
    profile_roots.reset_profile_roots_cache_for_tests()


@pytest.fixture
def read(monkeypatch):
    def run(record, epoch=1):
        monkeypatch.setattr(listing_attention, "registry_for_session", lambda **_k: record)
        return listing_attention.attention_reads_for_name(
            "cloude_a", registry_index={}, session_started_epoch=epoch,
            claude_session_uuid=UUID, working_dir=WORKDIR,
        )[1]
    return run


def test_second_pass_does_no_full_scan(corpus, read):
    first = read(_record())
    assert first.absent and first.verdict == FACTS_UNREADABLE
    assert corpus.scans, "the first pass must scan"
    corpus.scans.clear()
    again = read(_record())
    assert again.absent
    assert corpus.scans == []


def test_a_file_that_appears_is_found_by_the_one_stat_recheck(corpus, read):
    read(_record())
    (corpus.root / SLUG / f"{UUID}.jsonl").write_text("")
    assert not read(_record()).absent


def test_status_change_invalidates(corpus, read):
    read(_record())
    corpus.scans.clear()
    read(_record(status="busy"))
    assert corpus.scans, "a changed status must re-scan"
    corpus.scans.clear()
    read(_record(status="busy", updated=T0 + timedelta(seconds=5)))
    assert corpus.scans, "a changed statusUpdatedAt must re-scan"


def test_pane_epoch_change_invalidates(corpus, read):
    read(_record(), epoch=1)
    corpus.scans.clear()
    read(_record(), epoch=2)
    assert corpus.scans


def test_account_root_is_searched(corpus, read, monkeypatch):
    other = corpus.tmp / "acct" / "projects"
    (other / SLUG).mkdir(parents=True)
    (other / SLUG / f"{UUID}.jsonl").write_text("")
    monkeypatch.setattr(
        transcript_roots, "claude_transcript_roots", lambda *a, **k: (corpus.root, other)
    )
    facts = read(_record())
    assert not facts.absent
    assert facts.verdict != FACTS_UNREADABLE


def test_unknown_registry_is_never_cached(corpus, read):
    unknown = SimpleNamespace(known=False, verdict="ok", status=None, status_updated_at=None)
    read(unknown)
    corpus.scans.clear()
    read(unknown)
    assert corpus.scans

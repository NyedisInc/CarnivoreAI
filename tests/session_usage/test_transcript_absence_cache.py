
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Iterator, List

import pytest

from src.core import session_transcript_presence as presence
from src.core.session_token_usage import transcript_absence
from src.core.session_token_usage.claude_reader import locate_transcript
from src.core.session_transcript_presence import CONVERSATION_ABSENT, CONVERSATION_PRESENT

FOLDERS = 200
ROWS = 13
CALLERS = 12
OLD_NS = 60_000_000_000


def uuid_n(n: int) -> str:
    return f"2629dba5-1111-4222-8333-{n:012d}"


def age(path: Path, *, back_ns: int = OLD_NS) -> None:
    when = time.time_ns() - back_ns
    os.utime(path, ns=(when, when))


@pytest.fixture
def clock() -> Iterator[List[float]]:
    now = [1000.0]
    real = transcript_absence._clock
    transcript_absence._clock = lambda: now[0]
    yield now
    transcript_absence._clock = real


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: List[float]) -> Path:
    root = tmp_path / "projects"
    for i in range(FOLDERS):
        (root / f"-proj-{i}").mkdir(parents=True)
    for child in root.iterdir():
        age(child)
    age(root)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("src.core.claude_config.transcript_roots.claude_transcript_roots", lambda *a, **k: (root,))
    monkeypatch.setattr("src.core.claude_config.profile_roots.profile_subdir_roots", lambda default, *a, **k: (root,))
    presence._found_paths.clear()
    presence._root_listings.clear()
    transcript_absence.forget_all()
    return root


@pytest.fixture
def touches(corpus: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[], int]:
    seen: List[str] = []
    prefix = str(corpus)

    def wrap(module: object, name: str) -> None:
        real = getattr(module, name)

        def counting(path, *args, **kwargs):
            if str(path).startswith(prefix):
                seen.append(f"{name}:{path}")
            return real(path, *args, **kwargs)

        monkeypatch.setattr(module, name, counting)

    for fn in ("stat", "lstat", "scandir", "listdir"):
        wrap(os, fn)
    real_iterdir = Path.iterdir

    def counting_iterdir(self: Path):
        if str(self).startswith(prefix):
            seen.append(f"iterdir:{self}")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", counting_iterdir)
    return lambda: len(seen)


def test_absent_rows_do_not_rescan_the_corpus_every_pass(corpus: Path, touches: Callable[[], int]) -> None:
    for row in range(ROWS):
        assert locate_transcript(uuid_n(row), working_dir="/nowhere").outcome == CONVERSATION_ABSENT
    measured = touches()
    for _pass in range(2):
        for row in range(ROWS):
            for _caller in range(CALLERS):
                assert locate_transcript(uuid_n(row), working_dir="/nowhere").outcome == CONVERSATION_ABSENT
    repeats = ROWS * CALLERS * 2
    assert (touches() - measured) <= 2 * repeats, f"{touches() - measured} corpus touches for {repeats} repeat lookups"
    assert measured < ROWS * (FOLDERS + 10) + 2 * FOLDERS, measured


def test_transcript_created_in_an_existing_folder_is_found_after_the_window(corpus: Path, clock: List[float]) -> None:
    uuid = uuid_n(1)
    assert locate_transcript(uuid, working_dir="/nowhere").outcome == CONVERSATION_ABSENT
    assert locate_transcript(uuid, working_dir="/nowhere").outcome == CONVERSATION_ABSENT
    target = corpus / "-proj-7"
    (target / f"{uuid}.jsonl").write_text("{}\n")
    age(target, back_ns=OLD_NS // 2)
    clock[0] += transcript_absence.STAMP_REUSE_SECONDS + 1
    found = locate_transcript(uuid, working_dir="/nowhere")
    assert found.outcome == CONVERSATION_PRESENT and found.path == target / f"{uuid}.jsonl"


def test_new_project_folder_is_found_at_once_even_inside_the_window(corpus: Path) -> None:
    uuid = uuid_n(2)
    assert locate_transcript(uuid, working_dir="/nowhere").outcome == CONVERSATION_ABSENT
    fresh = corpus / "-brand new project~x"
    fresh.mkdir()
    (fresh / f"{uuid}.jsonl").write_text("{}\n")
    age(fresh)
    age(corpus, back_ns=OLD_NS // 2)
    assert locate_transcript(uuid, working_dir="/nowhere").path == fresh / f"{uuid}.jsonl"


def test_renamed_folder_holding_the_transcript_is_found(corpus: Path, clock: List[float]) -> None:
    uuid = uuid_n(3)
    staging = corpus.parent / "elsewhere"
    staging.mkdir()
    (staging / f"{uuid}.jsonl").write_text("{}\n")
    assert locate_transcript(uuid, working_dir="/nowhere").outcome == CONVERSATION_ABSENT
    os.rename(staging / f"{uuid}.jsonl", corpus / "-proj-3" / f"{uuid}.jsonl")
    age(corpus / "-proj-3", back_ns=OLD_NS // 2)
    clock[0] += transcript_absence.STAMP_REUSE_SECONDS + 1
    assert locate_transcript(uuid, working_dir="/nowhere").outcome == CONVERSATION_PRESENT


def test_a_racy_corpus_is_never_remembered(corpus: Path, touches: Callable[[], int]) -> None:
    os.utime(corpus / "-proj-0")
    uuid = uuid_n(4)
    locate_transcript(uuid, working_dir="/nowhere")
    first = touches()
    locate_transcript(uuid, working_dir="/nowhere")
    assert touches() - first >= FOLDERS, "a racy corpus must be searched again, not remembered"


def test_an_unreadable_root_is_not_an_absence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: List[float]) -> None:
    missing = tmp_path / "nope"
    monkeypatch.setattr("src.core.claude_config.transcript_roots.claude_transcript_roots", lambda *a, **k: (missing,))
    transcript_absence.forget_all()
    assert locate_transcript(uuid_n(5), working_dir="/x").outcome == "unchecked"
    assert transcript_absence.known_absent(uuid_n(5), ()) is None


def test_a_folder_locked_then_unlocked_is_not_stuck_absent(corpus: Path, clock: List[float]) -> None:
    if os.geteuid() == 0:
        pytest.skip("root reads a mode-0 folder")
    uuid = uuid_n(6)
    locked = corpus / "-proj-7"
    (locked / f"{uuid}.jsonl").write_text("{}\n")
    age(locked)
    os.chmod(locked, 0)
    try:
        assert locate_transcript(uuid, working_dir="/nowhere").outcome != CONVERSATION_PRESENT
    finally:
        os.chmod(locked, 0o755)
    clock[0] += transcript_absence.STAMP_REUSE_SECONDS + 1
    assert locate_transcript(uuid, working_dir="/nowhere").outcome == CONVERSATION_PRESENT


def test_a_recently_changed_folder_costs_no_more_than_no_cache(corpus: Path, touches: Callable[[], int], monkeypatch: pytest.MonkeyPatch) -> None:
    os.utime(corpus / "-proj-0")
    uuid, lookups = uuid_n(7), 10
    for _ in range(lookups):
        locate_transcript(uuid, working_dir="/nowhere")
    cached = touches()
    monkeypatch.setattr(transcript_absence, "stamps_for", lambda roots: None)
    before = touches()
    for _ in range(lookups):
        locate_transcript(uuid, working_dir="/nowhere")
    uncached = touches() - before
    assert cached <= uncached + lookups + 5, f"{cached} touches with the cache against {uncached} without"

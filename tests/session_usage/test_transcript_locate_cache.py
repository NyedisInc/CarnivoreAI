
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterator, List

import pytest

from src.core import session_transcript_presence as presence
from src.core.session_token_usage.claude_reader import locate_transcript

UUID = "2629dba5-1111-4222-8333-444455556666"


OLD_NS = 10_000_000_000


def age_root(root: Path, *, back_ns: int = OLD_NS) -> None:
    when = time.time_ns() - back_ns
    os.utime(root, ns=(when, when))


@pytest.fixture(autouse=True)
def clean_caches() -> Iterator[None]:
    presence._found_paths.clear()
    presence._root_listings.clear()
    yield
    presence._found_paths.clear()
    presence._root_listings.clear()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    projects = tmp_path / "projects"
    (projects / "-a").mkdir(parents=True)
    (projects / "-odd name~x").mkdir()
    (projects / "-odd name~x" / f"{UUID}.jsonl").write_text("{}\n")
    age_root(projects)
    return projects


@pytest.fixture
def listings(monkeypatch: pytest.MonkeyPatch) -> List[Path]:
    calls: List[Path] = []
    real = Path.iterdir

    def counting(self: Path) -> Iterator[Path]:
        calls.append(self)
        return real(self)

    monkeypatch.setattr(Path, "iterdir", counting)
    return calls


def test_repeated_lookup_lists_the_root_once(root: Path, listings: List[Path]) -> None:
    for _ in range(10):
        found = locate_transcript(UUID, working_dir="/nowhere", projects_dir=root)
        assert found.path == root / "-odd name~x" / f"{UUID}.jsonl"
    assert len([c for c in listings if c == root]) <= 1


def test_moved_transcript_is_found_again(root: Path) -> None:
    first = locate_transcript(UUID, projects_dir=root)
    moved = root / "-a" / f"{UUID}.jsonl"
    first.path.rename(moved)
    assert locate_transcript(UUID, projects_dir=root).path == moved


def test_not_found_turns_into_found_in_existing_folder(root: Path) -> None:
    other = "aaaaaaaa-1111-4222-8333-444455556666"
    assert locate_transcript(other, projects_dir=root).outcome == presence.CONVERSATION_ABSENT
    (root / "-a" / f"{other}.jsonl").write_text("{}\n")
    assert locate_transcript(other, projects_dir=root).path == root / "-a" / f"{other}.jsonl"


def test_not_found_turns_into_found_in_new_folder(root: Path) -> None:
    other = "bbbbbbbb-1111-4222-8333-444455556666"
    assert locate_transcript(other, projects_dir=root).outcome == presence.CONVERSATION_ABSENT
    new = root / "-new"
    new.mkdir()
    (new / f"{other}.jsonl").write_text("{}\n")
    assert locate_transcript(other, projects_dir=root).path == new / f"{other}.jsonl"


def test_repeated_misses_list_the_root_once(root: Path, listings: List[Path]) -> None:
    other = "cccccccc-1111-4222-8333-444455556666"
    for _ in range(10):
        assert locate_transcript(other, projects_dir=root).outcome == presence.CONVERSATION_ABSENT
    assert len([c for c in listings if c == root]) == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unreadable_root_after_cached_listing_is_unchecked_not_absent(root: Path) -> None:
    other = "dddddddd-1111-4222-8333-444455556666"
    assert locate_transcript(other, projects_dir=root).outcome == presence.CONVERSATION_ABSENT
    mtime = root.stat().st_mtime_ns
    root.chmod(0)
    try:
        os.utime(root, ns=(mtime, mtime))
        assert locate_transcript(other, projects_dir=root).outcome == presence.CONVERSATION_UNCHECKED
    finally:
        root.chmod(0o755)


def test_same_tick_folder_creation_is_found(root: Path) -> None:
    other = "eeeeeeee-1111-4222-8333-444455556666"
    age_root(root, back_ns=0)
    tick = root.stat().st_mtime_ns
    assert locate_transcript(other, projects_dir=root).outcome == presence.CONVERSATION_ABSENT
    new = root / "-same-tick"
    new.mkdir()
    (new / f"{other}.jsonl").write_text("{}\n")
    os.utime(root, ns=(tick, tick))
    assert locate_transcript(other, projects_dir=root).path == new / f"{other}.jsonl"


def test_second_copy_in_new_folder_restores_sorted_first_answer(root: Path) -> None:
    assert locate_transcript(UUID, projects_dir=root).path.parent.name == "-odd name~x"
    first = root / "-0-migrated"
    first.mkdir()
    (first / f"{UUID}.jsonl").write_text("{}\n")
    assert locate_transcript(UUID, projects_dir=root).path == first / f"{UUID}.jsonl"

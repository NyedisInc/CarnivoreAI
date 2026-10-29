
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from src.core.crate_format.errors import ConversationNotInCrate, DestinationInsideHome, DestinationNotEmpty
from src.core.crate_format.extract import extract_all, extract_conversation
from src.core.crate_format.reader import open_crate
from tests.python.crate_format.helpers import CODEX_CONV, CONV, ENC, build_crate, conversations, default_files


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def crate(tmp_path: Path) -> Path:
    return build_crate(tmp_path / "a.crate", target=64)


def test_claude_conversation_lands_in_the_recorded_layout(crate: Path, tmp_path: Path) -> None:
    with open_crate(crate) as reader:
        result = extract_conversation(reader, CONV, tmp_path / "out")
    assert result.enc_folder == ENC and result.resume_hint == f"claude --resume {CONV}"
    by_rel = {f.rel: f for f in default_files()}
    assert sorted(result.files) == sorted(r for r, f in by_rel.items() if f.conversation_id == CONV)
    for rel in result.files:
        on_disk = result.dest / rel
        assert on_disk.read_bytes() == by_rel[rel].data
        assert os.stat(on_disk).st_mtime_ns == by_rel[rel].mtime_ns
        assert os.stat(on_disk).st_mode & 0o777 == by_rel[rel].mode
    assert (result.dest / "projects" / ENC / f"{CONV}.jsonl").is_file()
    assert oct(os.stat(result.dest).st_mode & 0o777) == oct(0o700)


def test_enc_for_files_under_todays_rule(crate: Path, tmp_path: Path) -> None:
    with open_crate(crate) as reader:
        result = extract_conversation(reader, CONV, tmp_path / "out", enc_for=lambda wd: "-NEW" + wd.replace("/", "-"))
    assert result.enc_folder == "-NEW-Users-x-app"
    assert (result.dest / "projects" / "-NEW-Users-x-app" / f"{CONV}.jsonl").is_file()
    assert not (result.dest / "projects" / ENC).exists()
    assert (result.dest / "file-history" / CONV / "abc@v1").is_file()


def test_codex_conversation_keeps_its_rel_and_has_no_hint(crate: Path, tmp_path: Path) -> None:
    with open_crate(crate) as reader:
        result = extract_conversation(reader, CODEX_CONV, tmp_path / "out")
    assert result.resume_hint is None and result.enc_folder is None
    assert result.files == [f"sessions/2026/10/17/rollout-x-{CODEX_CONV}.jsonl"]


def test_share_lands_under_shared_with_a_two_step_hint(tmp_path: Path) -> None:
    convs = conversations()
    convs[0].update(working_dir=None, enc_folder=None, resume="fork_only")
    crate = build_crate(tmp_path / "s.crate", variant="share", convs=convs)
    with open_crate(crate) as reader:
        plain = extract_conversation(reader, CONV, tmp_path / "out")
        targeted = extract_conversation(reader, CONV, tmp_path / "out2", enc_for=lambda wd: "-T", target_cwd="/t")
    assert (plain.dest / "projects" / "_shared" / f"{CONV}.jsonl").is_file()
    assert "move projects/_shared/" in plain.resume_hint and "--fork-session" in plain.resume_hint
    assert targeted.resume_hint == f"claude --resume {CONV} --fork-session"
    assert (targeted.dest / "projects" / "-T" / f"{CONV}.jsonl").is_file()


def test_target_cwd_needs_enc_for(crate: Path, tmp_path: Path) -> None:
    with open_crate(crate) as reader, pytest.raises(ValueError):
        extract_conversation(reader, CONV, tmp_path / "out", target_cwd="/t")
    assert not (tmp_path / "out").exists()


def test_destination_must_not_exist(crate: Path, tmp_path: Path) -> None:
    (tmp_path / "out").mkdir()
    with open_crate(crate) as reader, pytest.raises(DestinationNotEmpty):
        extract_conversation(reader, CONV, tmp_path / "out")


def test_destination_inside_a_home_is_refused_even_through_a_symlink(crate: Path, tmp_path: Path) -> None:
    home = tmp_path / "home" / ".claude"
    home.mkdir(parents=True)
    (tmp_path / "alias").symlink_to(home)
    with open_crate(crate) as reader:
        for dest in (home / "projects", tmp_path / "alias" / "x"):
            with pytest.raises(DestinationInsideHome):
                extract_conversation(reader, CONV, dest, forbidden_roots=[home])
    assert list(home.iterdir()) == []


def test_unknown_conversation(crate: Path, tmp_path: Path) -> None:
    with open_crate(crate) as reader, pytest.raises(ConversationNotInCrate):
        extract_conversation(reader, "nope", tmp_path / "out")


def test_extract_all_writes_every_file_by_home(crate: Path, tmp_path: Path) -> None:
    with open_crate(crate) as reader:
        result = extract_all(reader, tmp_path / "all")
    expected = {f"{f.home}/{f.rel}": f.data for f in default_files()}
    assert sorted(result.files) == sorted(expected)
    for place, data in expected.items():
        assert (result.dest / place).read_bytes() == data

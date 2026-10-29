
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from src.cplugs.reviewboard import document
from src.cplugs.reviewboard.cli import scan as scan_cli
from src.cplugs.reviewboard.scan import MARKER, scan
from tests.python.cplugs.reviewboard.boards import PAGE, SIDECAR, make_board, make_root, sidecar


def _codes(result) -> set:
    return {f.code for f in result.findings}


def test_a_sound_board_scans_clean(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    make_board(root)
    result = scan(root)
    assert (result.exit_code, result.findings) == (0, ())
    row = result.boards[0]
    assert (row.slug, row.status, row.task_item_id, row.revisions, row.latest_file, row.rounds, row.last_round_at) == (
        "20261013-bottom-bar", "ok", 526, 1, "r001.html", 1, "2026-10-13T14:20:40Z")
    assert row.etag == document.etag((root / "20261013-bottom-bar" / "sidecar.json").read_bytes())


def test_a_revision_file_that_changed_is_an_error(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    folder = make_board(root)
    (folder / "r001.html").write_bytes(PAGE.replace(b"send", b"SEND"))
    result = scan(root)
    assert result.exit_code == 1 and "hash_mismatch" in _codes(result) and result.boards[0].status == "invalid"


@pytest.mark.parametrize("prepare", ["missing", "file", "no_marker", "empty", "symlink"])
def test_a_root_that_cannot_be_scanned_exits_2(tmp_path: Path, prepare: str) -> None:
    root = tmp_path / "boards"
    if prepare == "file":
        root.write_text("x")
    elif prepare == "no_marker":
        root.mkdir()
        make_board(root)
    elif prepare == "empty":
        make_root(tmp_path)
        (root / "README.md").write_text("hello\n")
    elif prepare == "symlink":
        (tmp_path / "real").mkdir()
        real = make_root(tmp_path / "real")
        make_board(real)
        os.symlink(real, root)
    result = scan(root)
    assert result.exit_code == 2 and result.root_error and result.boards == ()
    out = io.StringIO()
    assert scan_cli.main([str(root)], out=out) == 2 and out.getvalue().startswith("could not scan")


def test_files_the_sidecar_does_not_name_are_reported_never_deleted(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    folder = make_board(root)
    (folder / "r002.html").write_bytes(b"orphan")
    (folder / "ext-themes-cache.json").write_text("{}")
    (root / "notes.txt").write_text("stray")
    result = scan(root)
    assert result.exit_code == 0 and _codes(result) == {"orphan", "unknown_entry"}
    assert (folder / "r002.html").exists() and (root / "notes.txt").exists()


def test_a_symlinked_view_file_is_never_followed(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    folder = make_board(root)
    (tmp_path / "elsewhere.html").write_bytes(PAGE)
    (folder / "r001.html").unlink()
    os.symlink(tmp_path / "elsewhere.html", folder / "r001.html")
    assert "missing_file" in _codes(scan(root))


def test_the_folder_name_must_equal_the_slug(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    make_board(root).rename(root / "20261013-other")
    result = scan(root)
    assert result.exit_code == 1 and "slug_mismatch" in _codes(result)


def test_a_board_from_a_newer_build_is_listed_read_only(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    folder = root / "20261013-future"
    folder.mkdir()
    (folder / "sidecar.json").write_text(json.dumps({"schema": "carnivore.reviewboard.sidecar", "schema_version": 3, "new": 1}))
    result = scan(root)
    assert result.exit_code == 0 and result.boards[0].status == "newer" and _codes(result) == {"newer"}


def test_an_invalid_or_unreadable_sidecar_is_an_error_with_every_problem(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    broken = sidecar(rounds=[])
    broken["revisions"][0]["prompts"][0]["anchor"] = "nowhere"
    broken["revisions"][0]["anchors"] = [{"id": "a", "label": "x"}, {"id": "a", "label": "y"}]
    make_board(root, broken, canonical=False)
    unreadable = root / "20261013-unreadable"
    unreadable.mkdir()
    (unreadable / "sidecar.json").write_text("{not json")
    result = scan(root)
    messages = [f.message for f in result.findings if f.code == "invalid"]
    assert result.exit_code == 1 and len(messages) == 2 and "unreadable" in _codes(result)


def test_a_hand_edit_that_stays_valid_is_flagged_not_canonical(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    make_board(root, SIDECAR, canonical=False)
    result = scan(root)
    assert result.exit_code == 0 and _codes(result) == {"not_canonical"}


def test_the_command_line_prints_the_table_and_the_exit_code(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    folder = make_board(root)
    out = io.StringIO()
    assert scan_cli.main([str(root)], out=out) == 0
    lines = out.getvalue().splitlines()
    assert lines[0].split() == ["board", "status", "task", "revisions", "newest", "file", "rounds", "last", "round"]
    assert lines[1].split()[:3] == ["20261013-bottom-bar", "ok", "526"] and "Harbor666/CarnivoreAIDev#1700" in lines[1]
    (folder / "r001.html").write_bytes(b"changed")
    out = io.StringIO()
    assert scan_cli.main([str(root)], out=out) == 1 and "[hash_mismatch]" in out.getvalue()
    assert (root / MARKER).exists()


def _copy_board(root: Path, slug: str) -> Path:
    source = Path(__file__).resolve().parents[4] / "design" / "boards" / slug
    folder = root / slug
    folder.mkdir()
    for entry in source.iterdir():
        (folder / entry.name).write_bytes(entry.read_bytes())
    return folder


def test_one_unreadable_board_never_hides_the_others(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    make_board(root)
    view = _copy_board(root, "20261012-target-flow") / "r002.html"
    side = _copy_board(root, "20261012-current-flow") / "sidecar.json"
    locked = root / "20261013-locked"
    locked.mkdir()
    (locked / "sidecar.json").write_bytes((root / "20261013-bottom-bar" / "sidecar.json").read_bytes())
    for path, mode in ((view, 0), (side, 0), (locked, 0o300)):
        path.chmod(mode)
    try:
        result = scan(root)
    finally:
        for path, mode in ((view, 0o644), (side, 0o644), (locked, 0o755)):
            path.chmod(mode)
    unreadable = {f.board for f in result.findings if f.code == "unreadable"}
    assert result.exit_code == 1 and unreadable == {"20261012-target-flow", "20261012-current-flow", "20261013-locked"}
    assert [(b.slug, b.status) for b in result.boards] == [
        ("20261012-current-flow", "invalid"), ("20261012-target-flow", "invalid"), ("20261013-bottom-bar", "ok"),
        ("20261013-locked", "invalid")]


def test_a_root_that_cannot_be_listed_exits_2(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    make_board(root)
    root.chmod(0o300)
    try:
        result = scan(root)
    finally:
        root.chmod(0o755)
    assert result.exit_code == 2 and "could not be listed" in (result.root_error or "")


@pytest.mark.parametrize("text", ["[" * 200000 + "]" * 200000, None], ids=["deep_nesting", "huge_file_name"])
def test_a_malformed_sidecar_is_that_boards_finding_never_a_crash(tmp_path: Path, text: object) -> None:
    root = make_root(tmp_path)
    make_board(root)
    bad = root / "20261013-bad"
    bad.mkdir()
    if text is None:
        raw = sidecar(board={**SIDECAR["board"], "slug": "20261013-bad"})
        raw["revisions"][0]["views"][0]["file"] = "r" + "1" * 5000 + ".html"
        text = json.dumps(raw)
    (bad / "sidecar.json").write_text(str(text))
    result = scan(root)
    assert result.exit_code == 1 and {b.slug: b.status for b in result.boards} == {"20261013-bad": "invalid", "20261013-bottom-bar": "ok"}
    assert {f.code for f in result.findings} <= {"unreadable", "invalid"}


def test_a_folder_name_ending_in_a_newline_is_not_a_slug(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    make_board(root).rename(root / "20261013-bottom-bar\n")
    assert "bad_folder" in _codes(scan(root))


def test_a_file_many_revisions_share_is_read_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_root(tmp_path)
    _copy_board(root, "20261012-current-flow")
    reads: list = []
    real = Path.read_bytes

    def counted(self: Path) -> bytes:
        reads.append(self.name)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", counted)
    result = scan(root)
    assert result.exit_code == 0 and reads.count("r003.html") == 1 and reads.count("r003--journeys.html") == 1


def test_an_unchanged_view_file_is_hashed_once_and_a_changed_one_again(tmp_path: Path, monkeypatch) -> None:
    from src.cplugs.reviewboard import scan as scan_module
    scan_module._DIGESTS.clear()
    path = tmp_path / "view.html"
    path.write_bytes(b"<p>one</p>")
    reads: list[Path] = []
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: reads.append(self) or real(self))
    first = scan_module._digest(path, path.lstat())
    assert scan_module._digest(path, path.lstat()) == first and len(reads) == 1
    path.write_bytes(b"<p>two</p>")
    assert scan_module._digest(path, path.lstat()) != first and len(reads) == 2

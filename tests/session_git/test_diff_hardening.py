
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.core.session_git.diff import MAX_BYTES, EscapesRepository, _read_contained, read_file_diff
from src.core.session_git.reader import read_session_git
from src.core.session_git.watch import signature
from src.models.session_git import GitFile
from tests.session_git.test_reader import g, make_repo


@pytest.mark.parametrize("name", ["AuthKey_X.p8", "id_ecdsa", ".ENV", "a.P12", ".npmrc", "prod.tfvars", ".aws/credentials"])
def test_secret_names_show_name_only(tmp_path: Path, name: str) -> None:
    repo = make_repo(tmp_path / "r")
    f = repo / name
    f.parent.mkdir(exist_ok=True)
    f.write_text("hello\n")
    d = read_file_diff(repo, GitFile(path=name, kind="untracked"), staged=False, unborn=False)
    assert d.sensitive and not d.text


def test_renamed_secret_and_vendor_backstop(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r")
    (repo / "n.txt").write_text("k=ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8" + "\n")  # synthetic test value, never issued
    d = read_file_diff(repo, GitFile(path="n.txt", kind="untracked"), staged=False, unborn=False)
    assert d.sensitive and not d.text
    e = GitFile(path="plain.txt", orig_path=".env", kind="renamed")
    assert read_file_diff(repo, e, staged=False, unborn=False).sensitive


def test_repo_config_never_executes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r")
    mark = tmp_path / "marker"
    g(repo, "config", "core.fsmonitor", f"touch {mark}; echo")
    g(repo, "config", "filter.x.clean", f"touch {mark}; cat")
    (repo / ".gitattributes").write_text("a.txt filter=x\n")
    (repo / "a.txt").write_text("changed\n")
    read_session_git(repo)
    d = read_file_diff(repo, GitFile(path="a.txt", kind="modified"), staged=False, unborn=False)
    assert d.state == "ok" and "changed" in d.text
    assert not mark.exists()


def test_non_utf8_path_is_json_safe(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r")
    blob = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD:a.txt"], check=True, capture_output=True).stdout.strip()
    subprocess.run(["git", "-C", str(repo), "update-index", "--index-info"], check=True,
                   input=b"100644 " + blob + b"\tcaf\xe9.txt\n")
    status = read_session_git(repo)
    assert status.state == "ok"
    signature(status)
    status.model_dump_json()


def test_symlink_loop_is_escape_not_500(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r")
    (repo / "loop").symlink_to("loop")
    with pytest.raises(EscapesRepository):
        read_file_diff(repo, GitFile(path="loop", kind="untracked"), staged=False, unborn=False)


def test_big_diff_truncates_not_unknown(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r")
    (repo / "a.txt").write_text("line of text\n" * 800_000)
    d = read_file_diff(repo, GitFile(path="a.txt", kind="modified"), staged=False, unborn=False)
    assert d.state == "ok" and d.truncated and 0 < len(d.text.encode()) <= MAX_BYTES


def test_untracked_truncated_flag_covers_the_prefix_overflow(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r")
    (repo / "u.txt").write_text("123456789\n" * 25_000)
    d = read_file_diff(repo, GitFile(path="u.txt", kind="untracked"), staged=False, unborn=False)
    assert d.state == "ok" and len(d.text.encode()) == MAX_BYTES and d.truncated is True


def test_unborn_default_view_includes_working_tree_edits(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r", commit=False)
    (repo / "s.txt").write_text("staged\n")
    g(repo, "add", "s.txt")
    (repo / "s.txt").write_text("staged\nedited after staging\n")
    entry = GitFile(path="s.txt", kind="added")
    everything = read_file_diff(repo, entry, staged=False, unborn=True)
    only_staged = read_file_diff(repo, entry, staged=True, unborn=True)
    assert "+edited after staging" in everything.text and "+staged" in everything.text
    assert "edited after staging" not in only_staged.text


def test_untracked_read_refuses_swap_to_symlink_fifo_and_outside_descriptor(tmp_path: Path, monkeypatch) -> None:
    import os
    from src.core.session_git import diff as diff_mod
    repo = make_repo(tmp_path / "r")
    outside = tmp_path / "secret.txt"
    outside.write_text("outside\n")
    (repo / "link").symlink_to(outside)
    with pytest.raises(EscapesRepository):
        diff_mod._read_contained(repo, "link")
    os.mkfifo(repo / "pipe")
    with pytest.raises(EscapesRepository):
        diff_mod._read_contained(repo, "pipe")
    (repo / "ok.txt").write_text("fine\n")
    assert diff_mod._read_contained(repo, "ok.txt") == b"fine\n"
    monkeypatch.setattr(diff_mod, "_fd_real_path", lambda fd: str(outside))
    with pytest.raises(EscapesRepository):
        diff_mod._read_contained(repo, "ok.txt")


def test_untracked_hardlink_to_outside_file_is_refused(tmp_path: Path) -> None:
    import os
    repo = make_repo(tmp_path / "r")
    outside = tmp_path / "out.txt"
    outside.write_text("out\n")
    os.link(outside, repo / "hard.txt")
    with pytest.raises(EscapesRepository):
        _read_contained(repo, "hard.txt")

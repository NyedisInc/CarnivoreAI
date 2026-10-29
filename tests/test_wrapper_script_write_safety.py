from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from src.core.agent_wrappers import AgentWrapper, render_wrapper_invocation
from src.core.safe_file_write import SafeFileWriteError, UnsafeFileTargetError

SCRIPT = "keyc() (\n    claude \"$@\"\n)\n"


def _wrapper() -> AgentWrapper:
    return AgentWrapper(id="keyc", label="keyc", script=SCRIPT, entry="keyc")


def test_symlinked_script_file_is_refused_and_victim_untouched(tmp_path: Path) -> None:
    scripts = tmp_path / "agent_wrapper_scripts"
    scripts.mkdir(mode=0o700)
    victim = tmp_path / "victim.txt"
    victim.write_text("original\n")
    (scripts / "keyc.zsh").symlink_to(victim)

    with pytest.raises(UnsafeFileTargetError) as caught:
        render_wrapper_invocation(_wrapper(), scripts)

    assert caught.value.reason == "target_is_symlink"
    assert victim.read_text() == "original\n"
    assert (scripts / "keyc.zsh").is_symlink()


def test_dangling_symlink_is_refused_and_nothing_is_created(tmp_path: Path) -> None:
    scripts = tmp_path / "agent_wrapper_scripts"
    scripts.mkdir(mode=0o700)
    victim = tmp_path / "would-be-created.sh"
    (scripts / "keyc.zsh").symlink_to(victim)

    with pytest.raises(UnsafeFileTargetError):
        render_wrapper_invocation(_wrapper(), scripts)

    assert not victim.exists()


def test_symlinked_scripts_directory_is_refused(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    scripts = tmp_path / "agent_wrapper_scripts"
    scripts.symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(UnsafeFileTargetError) as caught:
        render_wrapper_invocation(_wrapper(), scripts)

    assert caught.value.reason == "directory_is_symlink"
    assert list(elsewhere.iterdir()) == []


def test_world_writable_scripts_directory_is_refused(tmp_path: Path) -> None:
    scripts = tmp_path / "agent_wrapper_scripts"
    scripts.mkdir()
    os.chmod(scripts, 0o777)

    with pytest.raises(UnsafeFileTargetError) as caught:
        render_wrapper_invocation(_wrapper(), scripts)

    assert caught.value.reason == "directory_foreign_writable"
    assert not (scripts / "keyc.zsh").exists()


def test_a_refusal_is_an_oserror_so_launch_callers_fail_the_launch(tmp_path: Path) -> None:
    assert issubclass(UnsafeFileTargetError, SafeFileWriteError)
    assert issubclass(SafeFileWriteError, OSError)


def test_normal_write_is_byte_exact_private_and_leaves_no_temp(tmp_path: Path) -> None:
    scripts = tmp_path / "state" / "agent_wrapper_scripts"

    outer = render_wrapper_invocation(_wrapper(), scripts)

    path = scripts / "keyc.zsh"
    assert str(path) in outer
    assert path.read_bytes() == SCRIPT.encode()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(scripts.stat().st_mode) == 0o700
    assert sorted(p.name for p in scripts.iterdir()) == ["keyc.zsh"]


def test_rewrite_replaces_the_inode_atomically(tmp_path: Path) -> None:
    scripts = tmp_path / "agent_wrapper_scripts"
    render_wrapper_invocation(_wrapper(), scripts)
    first = (scripts / "keyc.zsh").stat().st_ino
    held_open = open(scripts / "keyc.zsh", "rb")  # noqa: SIM115
    try:
        edited = AgentWrapper(id="keyc", label="keyc", script="keyc() { :; }\n", entry="keyc")
        render_wrapper_invocation(edited, scripts)
        assert held_open.read() == SCRIPT.encode()
    finally:
        held_open.close()
    assert (scripts / "keyc.zsh").stat().st_ino != first
    assert (scripts / "keyc.zsh").read_text() == "keyc() { :; }\n"
    assert stat.S_IMODE((scripts / "keyc.zsh").stat().st_mode) == 0o600


def test_mode_is_exact_under_a_permissive_umask(tmp_path: Path) -> None:
    scripts = tmp_path / "agent_wrapper_scripts"
    old = os.umask(0)
    try:
        render_wrapper_invocation(_wrapper(), scripts)
    finally:
        os.umask(old)
    assert stat.S_IMODE((scripts / "keyc.zsh").stat().st_mode) == 0o600
    assert stat.S_IMODE(scripts.stat().st_mode) == 0o700

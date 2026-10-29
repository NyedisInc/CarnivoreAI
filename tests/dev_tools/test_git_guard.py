
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.core.dev_tools import git_guard


@pytest.fixture(autouse=True)
def forget_cached_answers():
    yield
    git_guard._git_probe.drop()
    git_guard._usr_bin_probe.drop()


@pytest.fixture
def stock_mac(monkeypatch):
    execs: list = []

    def fake_run(argv, *a, **k):
        execs.append(list(argv))
        if argv[0].endswith("xcode-select"):
            return subprocess.CompletedProcess(argv, 2, "", "")
        raise AssertionError(f"executed {argv}: this is what raises Apple's install dialog")

    monkeypatch.setattr(git_guard.sys, "platform", "darwin")
    monkeypatch.setattr(git_guard.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(git_guard, "_developer_dir_has_git", lambda d: False)
    monkeypatch.setattr(git_guard.subprocess, "run", fake_run)
    monkeypatch.delenv("DEVELOPER_DIR", raising=False)
    git_guard.recheck()
    return execs


def test_missing_tools_never_run_the_shim_and_install_later_turns_git_on(stock_mac, monkeypatch):
    assert git_guard.git_available() is False
    assert not [a for a in stock_mac if a[0].endswith("/git")]
    monkeypatch.setattr(git_guard, "_developer_dir_has_git", lambda d: d == "/Library/Developer/CommandLineTools")
    assert git_guard.recheck() is True


def test_a_real_git_off_usr_bin_is_found_without_running_it(monkeypatch):
    monkeypatch.setattr(git_guard.shutil, "which", lambda name: "/opt/homebrew/bin/git")
    assert git_guard.recheck() is True


def test_every_caller_degrades_without_running_git(stock_mac, monkeypatch, tmp_path: Path):
    from src.core.swarm import say  # noqa: F401
    from src.core import config_files_ignore, update_check, version
    from src.core.pack.transport import ladder
    from src.core.session_git.reader import read_session_git
    from src.core.stats import rules
    from src.core.swarm import body_create, gitrun

    def boom(*a, **k):
        raise AssertionError("a subprocess started")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(git_guard, "_probe", lambda: False)
    git_guard._git_probe.drop()

    assert rules._git(tmp_path, ["rev-parse", "HEAD"]) == ""
    body_create.ensure_repo(str(tmp_path / "sysop"))
    assert (tmp_path / "sysop").is_dir() and not (tmp_path / "sysop" / ".git").exists()
    assert version.is_git_root(tmp_path) is False
    with pytest.raises(update_check.UpdateCheckError):
        update_check.fetch_remote_tags("https://example.invalid/r.git")
    assert read_session_git(tmp_path).state == "unknown"
    assert config_files_ignore.ignored_paths(tmp_path, ["./a"]) is None
    assert gitrun.run_git(tmp_path, "status", timeout=5, untrusted_repo=True).returncode == gitrun.NO_GIT_RC
    assert ladder.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], air_gap=False).returncode == 127


def test_a_hung_xcode_select_does_not_stall_concurrent_callers(monkeypatch):
    import threading
    import time

    started, release = threading.Event(), threading.Event()

    def hang(argv, *a, **k):
        started.set()
        release.wait(5)
        return subprocess.CompletedProcess(argv, 2, "", "")

    monkeypatch.setattr(git_guard.sys, "platform", "darwin")
    monkeypatch.setattr(git_guard.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(git_guard, "_developer_dir_has_git", lambda d: False)
    monkeypatch.setattr(git_guard.subprocess, "run", hang)
    git_guard._git_probe.drop()
    first = threading.Thread(target=git_guard.git_available)
    first.start()
    assert started.wait(2)
    began = time.monotonic()
    assert git_guard.git_available() is False
    waited = time.monotonic() - began
    release.set()
    first.join(5)
    assert waited < 1.0


def test_a_doubled_slash_shim_path_is_still_the_shim(stock_mac, monkeypatch):
    monkeypatch.setattr(git_guard.shutil, "which", lambda name: "/usr//bin/git")
    assert git_guard.recheck() is False


def test_the_pack_toolchain_snapshot_does_not_count_the_shims_as_tools(stock_mac, monkeypatch):
    from src.core.pack.machines import snapshot

    present = {"git": "/usr/bin/git", "python3": "/usr//bin/python3", "node": "/opt/homebrew/bin/node"}
    monkeypatch.setattr(git_guard.shutil, "which", lambda name: present.get(name))
    monkeypatch.setattr(git_guard, "_developer_dir_has_tool", lambda d, tool: False)
    tools = snapshot.read_toolchain()
    assert (tools["git"], tools["python3"], tools["node"]) == (False, False, True)
    assert all(argv[0].endswith("xcode-select") for argv in stock_mac)


def test_the_remaining_user_action_callers_degrade_without_running_git(stock_mac, monkeypatch, tmp_path: Path):
    import asyncio
    from src.core import project_worktree, secret_scan, server_status
    from src.core.project_pack import git_check
    from src.core.swarm import definition

    def boom(*a, **k):
        raise AssertionError("a subprocess started")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    monkeypatch.setattr(git_guard, "_probe", lambda: False)
    git_guard._git_probe.drop()

    assert secret_scan._git_tracked_files(tmp_path) is None
    with pytest.raises(project_worktree.GitUnavailable):
        asyncio.run(project_worktree.run_git(["status"]))
    (tmp_path / ".git").mkdir()
    assert server_status.collect_commit(tmp_path)["available"] is False
    with pytest.raises(git_check.GitReadError):
        git_check._git(str(tmp_path), "status")
    with pytest.raises(definition.SwarmFileError):
        definition.exclude_file(tmp_path)


def test_usr_bin_git_is_asked_about_itself_not_about_path(stock_mac, monkeypatch):
    monkeypatch.setattr(git_guard.shutil, "which", lambda name: "/opt/homebrew/bin/git")
    assert git_guard.recheck() is True
    assert git_guard.usr_bin_git_available() is False
    monkeypatch.setattr(git_guard, "_developer_dir_has_git", lambda d: d == "/Library/Developer/CommandLineTools")
    git_guard.recheck()
    assert git_guard.usr_bin_git_available() is True
    assert not [a for a in stock_mac if not a[0].endswith("xcode-select")]


def test_usr_bin_git_answer_is_cached_so_five_calls_probe_once(stock_mac):
    git_guard.recheck()
    stock_mac.clear()
    for _ in range(5):
        git_guard.usr_bin_git_available()
    assert len(stock_mac) <= 1


def test_usr_bin_git_ignores_developer_dir(stock_mac, monkeypatch):
    monkeypatch.setenv("DEVELOPER_DIR", "/somewhere/dev")
    monkeypatch.setattr(git_guard, "_developer_dir_has_git", lambda d: d == "/somewhere/dev")
    assert git_guard.recheck() is True
    assert git_guard.usr_bin_git_available() is False


def test_two_threads_on_a_cold_probe_both_get_the_real_answer():
    import threading
    import time

    started, results = threading.Event(), []

    def slow_probe() -> bool:
        started.set()
        time.sleep(0.3)
        return True

    probe = git_guard._TtlProbe(slow_probe)
    first = threading.Thread(target=lambda: results.append(probe.get()))
    first.start()
    assert started.wait(2)
    results.append(probe.get())
    first.join(5)
    assert results == [True, True]
    assert probe._probe_lock.acquire(blocking=False)
    probe._probe_lock.release()


def test_a_hung_cold_probe_does_not_stall_a_second_caller_forever(monkeypatch):
    import threading

    monkeypatch.setattr(git_guard, "_COLD_WAIT_S", 0.2)
    started, release = threading.Event(), threading.Event()

    def hung_probe() -> bool:
        started.set()
        release.wait(5)
        return True

    probe = git_guard._TtlProbe(hung_probe)
    first = threading.Thread(target=probe.get)
    first.start()
    assert started.wait(2)
    assert probe.get() is False
    release.set()
    first.join(5)


def test_an_expired_answer_is_still_served_at_once_while_a_probe_hangs(monkeypatch):
    import threading
    import time

    started, release = threading.Event(), threading.Event()

    def hung_probe() -> bool:
        started.set()
        release.wait(5)
        return False

    probe = git_guard._TtlProbe(hung_probe)
    probe._cached, probe._checked_at = True, time.monotonic() - 2 * git_guard._YES_TTL_S
    first = threading.Thread(target=probe.get)
    first.start()
    assert started.wait(2)
    began = time.monotonic()
    assert probe.get() is True
    assert time.monotonic() - began < git_guard._COLD_WAIT_S / 2
    release.set()
    first.join(5)


from __future__ import annotations

import os
import signal
import stat
from pathlib import Path

import pytest

from src.core.pack.jobs import agent_host
from src.core.pack.machines import probe


def _tool(folder: Path, name: str, body: str = "#!/bin/sh\nexit 0\n") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_a_tool_only_under_an_nvm_version_is_found_and_a_tool_nowhere_is_not(home: Path) -> None:
    _tool(home / ".nvm/versions/node/v22.1.0/bin", "codex")
    assert probe.find_tools([], home=home)["codex"] is True and probe.find_tools([], home=home)["ffmpeg"] is False
    assert probe.tool_present("codex", home=home) and not probe.tool_present("nosuchtool", home=home)
    assert agent_host.AgentDeps.harness_present("codex") and not agent_host.AgentDeps.harness_present("nosuchagent")


def test_a_dangling_link_is_not_a_tool(home: Path) -> None:
    folder = home / ".volta/bin"
    folder.mkdir(parents=True)
    os.symlink(home / "gone", folder / "codex")
    assert not probe.tool_present("codex", home=home)


def test_nothing_found_is_ever_run(home: Path) -> None:
    marker = home / "ran.txt"
    _tool(home / ".nvm/versions/node/v20.0.0/bin", "codex", f"#!/bin/sh\ntouch {marker}\n")
    assert probe.tool_present("codex", home=home) and probe.find_tools([], home=home)["codex"]
    assert not marker.exists()


@pytest.fixture()
def hard_timeout():
    def boom(_sig, _frame):
        raise TimeoutError("the lookup did not finish in 5 seconds")
    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(5)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)


def test_the_search_is_cut_at_64_folders_and_a_link_loop_does_not_hang(home: Path, hard_timeout) -> None:
    node = home / ".nvm/versions/node"
    for n in range(80):
        (node / f"v{n:03d}/bin").mkdir(parents=True)
    os.symlink(node, node / "bin")
    os.symlink(node, node / "loop")
    found = probe.version_manager_dirs(home)
    assert len(found) == probe.MAX_MANAGER_DIRS == 64 and found == sorted(found)
    assert str(node / "loop/bin") in found and str(node / "bin/bin") in found
    _tool(node / "v079/bin", "codex")
    assert not probe.tool_present("codex", home=home)


def test_a_link_pointing_outside_the_home_is_followed_and_never_run(home: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    marker = outside / "ran.txt"
    _tool(outside / "bin", "codex", f"#!/bin/sh\ntouch {marker}\n")
    (home / ".nvm/versions/node").mkdir(parents=True)
    os.symlink(outside, home / ".nvm/versions/node/vout")
    assert str(home / ".nvm/versions/node/vout/bin") in probe.version_manager_dirs(home)
    assert probe.tool_present("codex", home=home)
    assert not marker.exists()

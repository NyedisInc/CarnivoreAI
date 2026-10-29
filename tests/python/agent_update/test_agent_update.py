
from __future__ import annotations

from src.core.sessions.agent_update import (
    AgentUpdate,
    _parse_version,
    agent_update_status,
    forget_running_version,
    installed_claude_version,
    running_claude_version,
)


def _readers(running: str | None, installed: str | None):
    return (lambda pid: running), (lambda: installed)


def test_older_running_is_ready():
    running_reader, installed_reader = _readers("2.1.283", "2.1.284")
    result = agent_update_status(pid=123, running_reader=running_reader, installed_reader=installed_reader)
    assert result == AgentUpdate(running="2.1.283", installed="2.1.284", ready=True)


def test_equal_versions_not_ready():
    running_reader, installed_reader = _readers("2.1.284", "2.1.284")
    result = agent_update_status(pid=123, running_reader=running_reader, installed_reader=installed_reader)
    assert result == AgentUpdate(running="2.1.284", installed="2.1.284", ready=False)


def test_newer_running_not_ready():
    running_reader, installed_reader = _readers("2.1.285", "2.1.284")
    result = agent_update_status(pid=123, running_reader=running_reader, installed_reader=installed_reader)
    assert result == AgentUpdate(running="2.1.285", installed="2.1.284", ready=False)


def test_no_pid_is_unknown():
    running_reader, installed_reader = _readers("2.1.283", "2.1.284")
    assert agent_update_status(pid=None, running_reader=running_reader, installed_reader=installed_reader) is None


def test_unreadable_running_is_unknown():
    running_reader, installed_reader = _readers(None, "2.1.284")
    assert agent_update_status(pid=123, running_reader=running_reader, installed_reader=installed_reader) is None


def test_unreadable_installed_is_unknown():
    running_reader, installed_reader = _readers("2.1.283", None)
    assert agent_update_status(pid=123, running_reader=running_reader, installed_reader=installed_reader) is None


def test_malformed_version_string_is_unknown():
    running_reader, installed_reader = _readers("nightly", "2.1.284")
    assert agent_update_status(pid=123, running_reader=running_reader, installed_reader=installed_reader) is None


def test_parse_version_rejects_non_version_names():
    assert _parse_version("2.1.283") == (2, 1, 283)
    assert _parse_version("nightly") is None
    assert _parse_version(None) is None
    assert _parse_version("2.1") is None
    assert _parse_version("2.1.283-beta") is None


def test_installed_claude_version_reads_symlink_basename(tmp_path):
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    target = versions_dir / "2.1.284"
    target.write_bytes(b"\x00")
    link = tmp_path / "claude"
    link.symlink_to(target)
    assert installed_claude_version(str(link)) == "2.1.284"


def test_installed_claude_version_rejects_non_version_target(tmp_path):
    link = tmp_path / "claude"
    link.symlink_to(tmp_path / "current")
    assert installed_claude_version(str(link)) is None


def test_running_claude_version_reads_through_path_reader():
    forget_running_version(999)
    path_reader = lambda pid: "/x/versions/2.1.283"
    assert running_claude_version(999, path_reader=path_reader) == "2.1.283"
    forget_running_version(999)


def test_running_claude_version_falls_back_to_cache_on_transient_miss():
    forget_running_version(1000)
    good_reader = lambda pid: "/x/versions/2.1.283"
    assert running_claude_version(1000, path_reader=good_reader) == "2.1.283"

    flaky_reader = lambda pid: None
    assert running_claude_version(1000, path_reader=flaky_reader) == "2.1.283"
    forget_running_version(1000)


def test_running_claude_version_unknown_with_no_cache():
    forget_running_version(1001)
    assert running_claude_version(1001, path_reader=lambda pid: None) is None

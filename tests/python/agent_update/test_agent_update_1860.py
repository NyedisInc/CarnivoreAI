
from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace

import structlog
from structlog.testing import capture_logs

from src.api import agent_update_listing
from src.core.sessions.agent_update import installed_claude_version
from src.models import SessionInfo

UNVERSIONED = "/Users/x/.local/share/claude/ClaudeCode.app/Contents/MacOS/claude"


def _versions_tree(tmp_path, link_to: str, versions=("2.1.299", "2.1.301", "2.1.302")):
    vdir = tmp_path / "share" / "versions"
    vdir.mkdir(parents=True)
    for name in versions:
        (vdir / name).write_text("bin")
    (tmp_path / "bin").mkdir()
    link = tmp_path / "bin" / "claude"
    link.symlink_to(vdir / link_to)
    return str(link)


def test_unversioned_binary_path_reads_the_registry_version(monkeypatch):
    real = agent_update_listing.agent_update_status
    monkeypatch.setattr(
        agent_update_listing, "agent_update_status",
        lambda **kw: real(**kw, running_reader=lambda pid: None, installed_reader=lambda: "2.1.302"),
    )
    registry = SimpleNamespace(known=True, pid=4242, version=(2, 1, 296))
    observation = SimpleNamespace(stale=False, evidence=SimpleNamespace(registry=registry))
    watcher = SimpleNamespace(observation_for=lambda session_id, now=None: observation)
    info = SessionInfo.model_construct(session=SimpleNamespace(id="ses_1"), agent_family="claude")
    update = agent_update_listing.agent_update_for(watcher, info, datetime.now(timezone.utc))
    assert update is not None
    assert (update.running, update.installed, update.ready) == ("2.1.296", "2.1.302", True)


def test_installed_is_the_newest_on_disk_not_the_symlink_target(tmp_path):
    link = _versions_tree(tmp_path, link_to="2.1.301")
    assert installed_claude_version(link) == "2.1.302"


def test_installed_ignores_stray_files_in_the_versions_dir(tmp_path):
    link = _versions_tree(tmp_path, link_to="2.1.301", versions=("2.1.301", "2.1.399.bak", "latest"))
    assert installed_claude_version(link) == "2.1.301"


def test_unmeasurable_installed_logs_a_warning_with_context(tmp_path):
    stray = tmp_path / "somewhere" / "claude"
    stray.parent.mkdir()
    stray.write_text("bin")
    link = tmp_path / "claude-link"
    os.symlink(stray, link)
    structlog.reset_defaults()
    with capture_logs() as logs:
        assert installed_claude_version(str(link)) is None
    warnings = [e for e in logs if e["log_level"] == "warning"]
    assert warnings and warnings[0]["link"] == str(link)
    assert "target" in warnings[0]

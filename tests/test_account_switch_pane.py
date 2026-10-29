
from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from src.config.provider_accounts import ProviderAccount
from src.core.account_switch.active import ActiveAccount
from src.core.account_switch.pane_account import (
    PaneProfile,
    UNREADABLE,
    account_for_profile,
    parse_show_environment,
    read_pane_profile,
    running_elsewhere,
)
from src.core.session_token_usage.account_resolve import accounts_for_profile_dir
from src.core.tmux_command_batch import environment_commands
from tests.socket_guard import TEST_SOCKET_NAME

VAR = "CLAUDE_CONFIG_DIR"


def test_parse_reads_a_set_a_removed_and_an_unset_variable(monkeypatch):
    monkeypatch.delenv(VAR, raising=False)
    assert parse_show_environment(b"CLAUDE_CONFIG_DIR=/p/work\n", 0, VAR) == PaneProfile(True, "/p/work")
    assert parse_show_environment(b"-CLAUDE_CONFIG_DIR\n", 0, VAR) == PaneProfile(True, None)
    assert parse_show_environment(b"", 1, VAR) == PaneProfile(True, None, inherited=True)
    assert parse_show_environment(b"", 2, VAR) == UNREADABLE


def _rows():
    return [
        ProviderAccount(id="work", name="w", provider="claude", claude_config_dir="/p/work"),
        ProviderAccount(id="play", name="p", provider="claude", claude_config_dir="/p/play"),
        ProviderAccount(id="cx", name="c", provider="codex", codex_home="/p/work"),
    ]


def test_a_pane_profile_names_exactly_one_account_of_its_provider():
    assert account_for_profile(_rows(), "claude", PaneProfile(True, "/p/work")) == "work"
    assert account_for_profile(_rows(), "claude", PaneProfile(True, "/p/elsewhere")) is None
    assert account_for_profile(_rows(), "claude", UNREADABLE) is None


def test_the_token_panel_names_a_switched_session_by_its_directory():
    matched = accounts_for_profile_dir(_rows(), provider="claude", profile_dir="/p/play")
    assert [a.id for a in matched] == ["play"]


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True, text=True)


@pytest.fixture()
def session():
    name = f"acsw_{uuid.uuid4().hex[:8]}"
    created = _tmux("new-session", "-d", "-s", name, "-e", f"{VAR}=/p/work", "sleep 60")
    assert created.returncode == 0, created.stderr
    yield name
    _tmux("kill-session", "-t", f"={name}")


def test_reading_a_real_pane_set_removed_and_gone(session, monkeypatch):
    monkeypatch.delenv(VAR, raising=False)
    assert asyncio.run(read_pane_profile(TEST_SOCKET_NAME, session, VAR)) == PaneProfile(True, "/p/work")
    _tmux("set-environment", "-t", f"={session}", "-r", VAR)
    assert asyncio.run(read_pane_profile(TEST_SOCKET_NAME, session, VAR)) == PaneProfile(True, None)
    assert asyncio.run(read_pane_profile(TEST_SOCKET_NAME, session + "_gone", VAR)) == UNREADABLE


class _Info:

    def __init__(self, name, family="claude", status="idle"):
        self.tmux_session = name
        self.agent_family = family
        self.activity_status = status
        self.label = "a label"
        self.session = type("S", (), {"id": f"id_{name}"})()


def test_a_session_on_another_account_is_listed_and_one_on_the_active_is_not(session):
    active = {"claude": ActiveAccount("claude", "play", "pointer", "play")}
    rows = asyncio.run(running_elsewhere(
        [_Info(session), _Info(session, family="shell"), _Info(session, status="dead")],
        socket=TEST_SOCKET_NAME, accounts=_rows(), active=active,
    ))
    assert [(r["session_id"], r["account_id"], r["active_account_id"]) for r in rows] == [
        (f"id_{session}", "work", "play"),
    ]
    same = {"claude": ActiveAccount("claude", "work", "pointer", "work")}
    assert asyncio.run(running_elsewhere(
        [_Info(session)], socket=TEST_SOCKET_NAME, accounts=_rows(), active=same,
    )) == []


def test_a_restart_with_remove_leaves_the_new_process_without_the_variable(session, tmp_path):
    out = tmp_path / "env.txt"
    for command in environment_commands(f"={session}", {VAR: None}):
        assert _tmux(*command).returncode == 0
    _tmux("respawn-pane", "-k", "-t", f"={session}:", f"env > {out}; sleep 30")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not (out.exists() and out.stat().st_size):
        time.sleep(0.05)
    body = out.read_text()
    assert "PATH=" in body, "the respawned process wrote nothing, so this proved nothing"
    assert VAR not in body


from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ph_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ph_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import pytest

from src.core.attention import codex_gather, codex_pane_home
from src.core.session_transcript_presence import CONVERSATION_ABSENT, CONVERSATION_PRESENT
from src.core.tmux_transport.lifecycle import LocalLifecycle

UUID = "019a1b2c-3d4e-7f60-8a9b-0c1d2e3f4a5b"


@pytest.fixture
def homes(tmp_path, monkeypatch):
    default = tmp_path / "default"
    (default / "sessions").mkdir(parents=True)
    account = tmp_path / "account"
    day = account / "sessions" / "2026" / "11" / "18"
    day.mkdir(parents=True)
    rollout = day / f"rollout-2026-11-18T17-46-28-{UUID}.jsonl"
    rollout.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(codex_gather, "DEFAULT_CODEX_HOME", str(default))
    monkeypatch.setattr(
        codex_pane_home, "pane_codex_home", lambda socket, name, identity=None: str(account)
    )
    return default, account, rollout


def _lifecycle() -> LocalLifecycle:
    backend = SimpleNamespace(socket_name="test-sock", tmux_session="carnivore_x", working_dir="/tmp/x")
    life = LocalLifecycle.__new__(LocalLifecycle)
    life._backend = backend
    return life


def test_helper_answers_the_pane_home_for_codex_and_none_otherwise(homes):
    _, account, _ = homes
    assert codex_pane_home.codex_home_for_row("codex", "s", "n") == str(account)
    assert codex_pane_home.codex_home_for_row("claude", "s", "n") is None
    assert codex_pane_home.codex_home_for_row(None, "s", "n") is None


def test_wake_presence_finds_a_rollout_only_under_the_account_home(homes):
    _, _, rollout = homes
    outcome, detail = asyncio.run(_lifecycle().resume_presence(UUID, "codex"))
    assert outcome == CONVERSATION_PRESENT, detail


def test_wake_presence_still_refuses_when_no_home_has_the_rollout(homes):
    outcome, _ = asyncio.run(_lifecycle().resume_presence("019a1b2c-3d4e-7f60-8a9b-ffffffffffff", "codex"))
    assert outcome == CONVERSATION_ABSENT

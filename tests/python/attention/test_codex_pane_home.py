
import os
import shutil
import subprocess
import uuid as uuidlib

import pytest

from tests.socket_guard import TEST_SOCKET_NAME

from src.core.attention import codex_pane_home as cph
from src.core.attention.codex_gather import DEFAULT_CODEX_HOME, rollout_path_in_sessions
from src.core.session_imported_restart import DIRECTORY_MEASURED, resume_directory
from src.core.session_sleep import _transcript_absent
from src.core.session_transcript_presence import CONVERSATION_PRESENT, family_conversation_presence

THREAD = str(uuidlib.uuid4())


@pytest.fixture(autouse=True)
def _fresh_cache():
    cph.clear_cache()
    yield
    cph.clear_cache()


def _relay_home(tmp_path):
    day = tmp_path / "relay-codex" / "sessions" / "2026" / "11" / "03"
    day.mkdir(parents=True)
    (day / f"rollout-2026-11-03T00-00-00-{THREAD}.jsonl").write_text("{}\n")
    return str(tmp_path / "relay-codex")


def _answer(monkeypatch, own, glob=None):
    def fake(socket, args):
        return glob if "-g" in args else own
    monkeypatch.setattr(cph, "_read_variable", fake)


def test_no_pane_means_default_home():
    assert cph.pane_codex_home(None, "carnivore_x") == DEFAULT_CODEX_HOME
    assert cph.pane_codex_home("cloude", None) == DEFAULT_CODEX_HOME


def test_removed_and_unreadable_pane_answer_default(monkeypatch):
    _answer(monkeypatch, (None, False))
    assert cph.pane_codex_home("s", "a") == DEFAULT_CODEX_HOME
    _answer(monkeypatch, None)
    assert cph.pane_codex_home("s", "b") == DEFAULT_CODEX_HOME


def test_unset_session_falls_to_server_global_then_default(monkeypatch):
    _answer(monkeypatch, (None, True), glob=("/srv/codex", False))
    assert cph.pane_codex_home("s", "a") == "/srv/codex"
    _answer(monkeypatch, (None, True), glob=(None, False))
    assert cph.pane_codex_home("s", "b") == DEFAULT_CODEX_HOME


def test_relative_value_is_not_trusted(monkeypatch):
    _answer(monkeypatch, ("relative/home", False))
    assert cph.pane_codex_home("s", "a") == DEFAULT_CODEX_HOME


def test_status_rollout_resume_follow_the_pane_home(monkeypatch, tmp_path):
    home = _relay_home(tmp_path)
    _answer(monkeypatch, (home, False))
    resolved = cph.pane_codex_home("s", "relay_pane")
    assert resolved == home
    assert rollout_path_in_sessions(resolved, THREAD)
    assert family_conversation_presence("codex", THREAD, codex_home=resolved).outcome == CONVERSATION_PRESENT
    assert resume_directory("/w", THREAD, family="codex", codex_home=resolved).outcome == DIRECTORY_MEASURED
    (tmp_path / "other" / "sessions").mkdir(parents=True)
    assert family_conversation_presence("codex", THREAD, codex_home=str(tmp_path / "other")).missing


def test_dead_pane_row_on_relay_home_is_not_absent(monkeypatch, tmp_path):
    home = _relay_home(tmp_path)
    _answer(monkeypatch, (home, False))
    row = {"agent_family": "codex", "tmux_socket": "s", "tmux_name": "relay_pane"}
    assert _transcript_absent(row, THREAD) is False


@pytest.mark.real_tmux
@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux missing")
def test_real_throwaway_socket(tmp_path):
    sock = TEST_SOCKET_NAME
    home = _relay_home(tmp_path)
    try:
        subprocess.run(["tmux", "-L", sock, "new-session", "-d", "-s", "relay", "-e", f"CODEX_HOME={home}", "sleep 30"], check=True)
        subprocess.run(["tmux", "-L", sock, "new-session", "-d", "-s", "plain", "sleep 30"], check=True)
        subprocess.run(["tmux", "-L", sock, "set-environment", "-t", "relay", "CODEX_HOME", home], check=True)
        assert cph.pane_codex_home(sock, "relay") == home
        assert cph.pane_codex_home(sock, "plain") == DEFAULT_CODEX_HOME
        assert cph.pane_codex_home(sock, "gone") == DEFAULT_CODEX_HOME
    finally:
        for name in ("relay", "plain"):
            subprocess.run(["tmux", "-L", sock, "kill-session", "-t", f"={name}"], check=False, capture_output=True)


from __future__ import annotations

import pytest

from src.core.launch_profiles import launch_failure
from src.core.sessions.errors import SessionCreateFailed, TmuxError

from .conftest import LEAK
from .test_session_routes_codes import _Boom, _assert_fixed

DEAD = TmuxError(f"agent failed to launch: zsh: command not found: claude {LEAK}")


def test_missing_claude_answers_its_own_sentence(driver, monkeypatch):
    monkeypatch.setattr(launch_failure, "harness_installed", lambda harness: False)
    response, events = driver.call("POST", "/sessions", _Boom(DEAD), json={})
    _assert_fixed(response, 502, "agent_not_installed_claude", events)
    assert response.json()["detail"]["detail"].startswith("claude is not installed on this computer")


@pytest.mark.parametrize("exc, agent, installed, code", [
    (DEAD, "codex", False, "agent_not_installed_codex"),
    (DEAD, None, True, "agent_exited"),
    (TmuxError("tmux was not found on PATH"), None, True, "tmux_missing"),
    (TmuxError("tmux new-session failed: x"), None, True, "session_launch_failed"),
])
def test_classifier(monkeypatch, exc, agent, installed, code):
    monkeypatch.setattr(launch_failure, "harness_installed", lambda harness: installed)
    assert launch_failure.classify_launch_failure(exc, agent) == code


def test_unusable_folder():
    exc = SessionCreateFailed("Failed to create session: x")
    exc.__cause__ = PermissionError("denied")
    assert launch_failure.classify_launch_failure(exc, None) == "workdir_unusable"


def test_pane_path_gets_the_native_install_dirs(tmp_path, monkeypatch):
    from src.core.launch_profiles import installed

    (tmp_path / ".local" / "bin").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    out = installed.path_with_install_dirs("/usr/bin:/bin")
    assert out.split(":")[:2] == ["/usr/bin", "/bin"] and str(tmp_path / ".local" / "bin") in out.split(":")
    assert installed.path_with_install_dirs(out) == out

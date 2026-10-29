
from __future__ import annotations

import inspect
import os
import tempfile

os.environ.setdefault(
    "DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_label_wd_")
)

import pytest

from src.core import claude_rename
from src.core.claude_rename import (
    MIN_RENAME_VERSION,
    launch_name_args,
    launch_name_args_for_agent_type,
)
from src.models import CreateSessionRequest

SUPPORTED = MIN_RENAME_VERSION


@pytest.fixture
def installed_claude_supports_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude_rename, "detect_claude_version", lambda: SUPPORTED)




def test_the_create_request_accepts_a_label():
    body = CreateSessionRequest(project_name="Punchlist", label="Punchlist")

    assert body.label == "Punchlist"


def test_a_label_is_optional_and_defaults_to_none():
    body = CreateSessionRequest(project_name="Punchlist")

    assert body.label is None


def test_the_label_is_separate_from_the_project_name():
    body = CreateSessionRequest(project_name="Infrastructure", label="Spike 3")

    assert body.project_name == "Infrastructure"
    assert body.label == "Spike 3"




def test_create_session_still_takes_a_label_argument():
    from src.core.session_manager import SessionManager

    params = inspect.signature(SessionManager.create_session).parameters

    assert "label" in params
    assert params["label"].default is None


def test_a_label_becomes_the_name_flag():
    assert launch_name_args(
        label="Punchlist Test", family="claude", claude_version=SUPPORTED
    ) == ["--name", "Punchlist Test"]


def test_no_label_adds_no_flag():
    assert launch_name_args(
        label=None, family="claude", claude_version=SUPPORTED
    ) == []
    assert launch_name_args(
        label="", family="claude", claude_version=SUPPORTED
    ) == []


def test_a_label_is_not_handed_to_a_non_claude_agent():
    assert launch_name_args(
        label="Punchlist", family="codex", claude_version=SUPPORTED
    ) == []
    assert launch_name_args(
        label="Punchlist", family="shell", claude_version=SUPPORTED
    ) == []


def test_a_claude_too_old_for_rename_gets_no_flag():
    assert launch_name_args(
        label="Punchlist", family="claude", claude_version=(2, 1, 100)
    ) == []
    assert launch_name_args(
        label="Punchlist", family="claude", claude_version=None
    ) == []


@pytest.mark.parametrize(
    "label",
    [
        "Punchlist Test",
        "Refactor spike (round 2)",
        "Garden Planner 2026",
    ],
)
def test_real_project_names_survive_as_one_argv_element(label):
    args = launch_name_args(label=label, family="claude", claude_version=SUPPORTED)

    assert args == ["--name", label]
    assert len(args) == 2


def test_the_agent_type_wrapper_resolves_the_family_itself(
    installed_claude_supports_name,
):
    args = launch_name_args_for_agent_type(label="Punchlist", agent_type="claude")

    assert args == ["--name", "Punchlist"]


def test_no_label_changes_nothing_on_the_id_path():
    assert launch_name_args_for_agent_type(label=None, agent_type="claude") == []
    assert launch_name_args_for_agent_type(label="", agent_type="claude") == []


def test_an_unknown_agent_type_gets_the_flag_because_claude_is_what_runs(
    installed_claude_supports_name,
):
    args = launch_name_args_for_agent_type(
        label="Punchlist", agent_type="not-a-configured-agent-xyz"
    )

    assert args == ["--name", "Punchlist"]


def test_a_shell_wrapper_id_never_gets_the_name_flag(installed_claude_supports_name):
    wrappers = [
        {"id": "shell-default", "family": "shell"},
        {"id": "codex-default", "family": "codex"},
        {"id": "claude-skip-permissions", "family": "claude"},
    ]

    assert launch_name_args_for_agent_type(
        label="Mini Terminal", agent_type="shell-default", wrappers=wrappers
    ) == []
    assert launch_name_args_for_agent_type(
        label="Mini Terminal", agent_type="codex-default", wrappers=wrappers
    ) == []
    assert launch_name_args_for_agent_type(
        label="Mini Terminal", agent_type="claude-skip-permissions", wrappers=wrappers
    ) == ["--name", "Mini Terminal"]

    from src.core import session_manager

    source = inspect.getsource(session_manager.SessionManager.create_session)
    assert "wrappers=_configured_wrappers()" in source

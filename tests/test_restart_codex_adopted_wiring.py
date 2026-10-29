
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

import src.core.attention.codex_stores as codex_stores  # noqa: E402
from src.core.attention.evidence import FAMILY_CODEX  # noqa: E402
from src.core.session_manager import SessionManager  # noqa: E402
from src.core.session_resume_target import (  # noqa: E402
    CONVERSATION_NONE_RECORDED,
    resume_extra_args,
    resume_target_from_row,
)

UUID = "ad166ca4-f8b4-989f-dee8-b5b4f34999e3"
NAME = "cloude_x"


def _stub_manager(sessions):
    stub = SimpleNamespace(_registry=SimpleNamespace(sessions=sessions, backends={}))
    stub._is_remote_sid = lambda sid: SessionManager._is_remote_sid(stub, sid)
    return stub


def _codex_none_target():
    row = {"claude_session_uuid": "", "agent_family": FAMILY_CODEX}
    return resume_target_from_row(row, row_read_ok=True)


def test_wiring_picks_live_and_uses_the_in_memory_cwd(monkeypatch):
    seen = {}

    def fake_pick(home, *, pane_current_path, pane_title):
        seen["cwd"] = pane_current_path
        return UUID

    monkeypatch.setattr(codex_stores, "resolve_primary_uuid", fake_pick)
    sessions = {
        "ses_1": SimpleNamespace(id="ses_1", tmux_session=NAME, working_dir="/live/cwd")
    }
    mgr = _stub_manager(sessions)

    out = SessionManager._codex_adopted_resume_upgrade(
        mgr, _codex_none_target(), NAME, row_working_dir="/row/cwd"
    )
    assert seen["cwd"] == "/live/cwd"
    assert resume_extra_args(out) == ["resume", UUID]


def test_wiring_falls_back_to_the_row_cwd(monkeypatch):
    seen = {}

    def fake_pick(home, *, pane_current_path, pane_title):
        seen["cwd"] = pane_current_path
        return UUID

    monkeypatch.setattr(codex_stores, "resolve_primary_uuid", fake_pick)
    mgr = _stub_manager({})
    out = SessionManager._codex_adopted_resume_upgrade(
        mgr, _codex_none_target(), NAME, row_working_dir="/row/cwd"
    )
    assert seen["cwd"] == "/row/cwd"
    assert resume_extra_args(out) == ["resume", UUID]


def test_wiring_is_fail_soft_when_the_store_read_raises(monkeypatch):
    def boom(home, *, pane_current_path, pane_title):
        raise RuntimeError("codex store unreadable")

    monkeypatch.setattr(codex_stores, "resolve_primary_uuid", boom)
    sessions = {
        "ses_1": SimpleNamespace(id="ses_1", tmux_session=NAME, working_dir="/live/cwd")
    }
    out = SessionManager._codex_adopted_resume_upgrade(
        _stub_manager(sessions), _codex_none_target(), NAME
    )
    assert out.outcome == CONVERSATION_NONE_RECORDED
    assert resume_extra_args(out) is None


def test_wiring_never_picks_for_a_claude_row(monkeypatch):
    def boom(home, *, pane_current_path, pane_title):
        raise AssertionError("the pick must not run for a claude row")

    monkeypatch.setattr(codex_stores, "resolve_primary_uuid", boom)
    row = {"claude_session_uuid": UUID, "agent_family": "claude"}
    target = resume_target_from_row(row, row_read_ok=True)
    sessions = {
        "ses_1": SimpleNamespace(id="ses_1", tmux_session=NAME, working_dir="/live/cwd")
    }
    out = SessionManager._codex_adopted_resume_upgrade(
        _stub_manager(sessions), target, NAME
    )
    assert resume_extra_args(out) == ["--resume", UUID]

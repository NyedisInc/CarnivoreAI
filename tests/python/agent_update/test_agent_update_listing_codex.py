
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from src.api import agent_update_listing
from src.core.claude_resume_argv import ProcessRow
from src.core.sessions.agent_update import AgentUpdate
from src.models import SessionInfo


def _codex_info():
    return SessionInfo.model_construct(
        session=SimpleNamespace(id="ses_c", pty_pid=500), agent_family="codex", claude_session_uuid=None,
    )


def test_codex_row_is_stamped_from_the_codex_check(monkeypatch):
    agent_update_listing._CODEX_ANSWERS.clear()
    monkeypatch.setattr(
        agent_update_listing, "codex_update_status",
        lambda **kw: AgentUpdate("0.141.0", "0.142.0", True), raising=False,
    )
    table = [ProcessRow(500, 1, "codex")]
    update = agent_update_listing.agent_update_for(None, _codex_info(), datetime.now(timezone.utc), table)
    assert update == AgentUpdate("0.141.0", "0.142.0", True)


def test_codex_row_without_a_process_table_is_null():
    agent_update_listing._CODEX_ANSWERS.clear()
    assert agent_update_listing.agent_update_for(None, _codex_info(), datetime.now(timezone.utc), None) is None


def test_other_family_stays_null():
    info = SessionInfo.model_construct(session=SimpleNamespace(id="ses_x", pty_pid=1), agent_family="gemini")
    assert agent_update_listing.agent_update_for(None, info, datetime.now(timezone.utc)) is None


from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from src.plugins.taskmanager import held, sending
from src.plugins.taskmanager.service import candidates

NOW = datetime(2026, 11, 17, 17, 0, tzinfo=timezone.utc)
LINE = "Login reached its time limit · Please run /login"


def _info(session_id: str, login: Any) -> Any:
    return SimpleNamespace(
        session=SimpleNamespace(id=session_id, last_activity=NOW), tmux_session="t", project_name="Fantasy Hockey 2026",
        project_id=7, activity_status="idle", agent_family="claude", label="hockey", login_expired=login)


def test_a_task_manager_tell_to_a_locked_out_session_is_refused_not_sent_and_not_held():
    rows = candidates([_info("ses_1", SimpleNamespace(message=LINE))], "7")
    assert rows[0]["login_expired"] is True
    ctx = SimpleNamespace()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(sending.paste_send(ctx, None, "7", "Fantasy Hockey 2026", rows, "ses_1", "scheduled", aggregate=False))
    assert held.refusal_code(caught.value) == "login_expired"
    assert "/login" in held.refusal_reason(caught.value)
    assert "login_expired" not in held.BUSY_CODES
    ok = candidates([_info("ses_2", None)], "7")
    assert ok[0]["login_expired"] is False
    sending.refuse_if_login_expired(ok, "ses_2")

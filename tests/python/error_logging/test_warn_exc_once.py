from __future__ import annotations

from structlog.testing import capture_logs

from src.core.sessions import agent_update_warn as warn


def test_same_cause_logs_once_and_a_new_cause_logs_again() -> None:
    warn.reset_warnings()
    with capture_logs() as logs:
        assert warn.warn_exc_once("store_unreadable", OSError("disk"), store="x") is True
        assert warn.warn_exc_once("store_unreadable", OSError("disk"), store="x") is False
        assert warn.warn_exc_once("store_unreadable", ValueError("bad json")) is True
    assert [l["error_type"] for l in logs] == ["OSError", "ValueError"]
    assert logs[0]["store"] == "x" and logs[0]["log_level"] == "warning"
    warn.reset_warnings()

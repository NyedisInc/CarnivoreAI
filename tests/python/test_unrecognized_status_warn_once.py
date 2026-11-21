from __future__ import annotations

from unittest.mock import patch

from src.models import sessions as sessions_model
from src.models.sessions import Session, SessionInfo


def _validate(status: str) -> SessionInfo:
    return SessionInfo.model_validate({"session": Session(id="ses_x", working_dir="/p").model_dump(), "activity_status": status})


def test_same_unknown_value_logs_once_and_a_new_one_logs_again() -> None:
    sessions_model._unrecognized_status_seen.clear()
    with patch.object(sessions_model.logger, "warning") as warn:
        assert _validate("hibernating").activity_status == "unknown"
        assert _validate("hibernating").activity_status == "unknown"
        assert warn.call_count == 1
        _validate("sleeping")
        assert warn.call_count == 2

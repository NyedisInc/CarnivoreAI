
from __future__ import annotations

from src.api.notification_destinations_routes import _errors
from src.core.notifications.destinations import store as store_mod

from .conftest import LEAK


def test_a_destination_store_failure_answers_a_code_and_logs_the_cause():
    import structlog

    with structlog.testing.capture_logs() as events:
        caught = _errors(store_mod.KeychainUnavailable(f"keychain locked {LEAK}"))
    assert caught.status_code == 503 and caught.detail["code"] == "destination_keychain_unavailable"
    assert LEAK not in str(caught.detail) and any(LEAK in str(e.get("error")) for e in events)


def test_an_unexpected_failure_is_a_write_failed_code_not_its_text():
    caught = _errors(RuntimeError(f"boom {LEAK}"))
    assert caught.status_code == 503 and caught.detail["code"] == "destination_write_failed"
    assert LEAK not in str(caught.detail)

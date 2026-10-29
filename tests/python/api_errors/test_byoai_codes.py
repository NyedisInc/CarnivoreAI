
from __future__ import annotations

from types import SimpleNamespace

import pytest
import structlog
from fastapi import HTTPException

from src.api.ai_common import api_errors
from src.core.byoai.contracts import ByoaiUnreachable, NotConfigured, ProviderHTTPError, ProviderTimeout

from .conftest import LEAK

GATEWAY = SimpleNamespace(store=SimpleNamespace(read=lambda: SimpleNamespace(revision=7)))


def _raise(exc: Exception) -> HTTPException:
    with structlog.testing.capture_logs() as events, pytest.raises(HTTPException) as caught:
        with api_errors(GATEWAY):
            raise exc
    caught.value.events = events  # type: ignore[attr-defined]
    return caught.value


@pytest.mark.parametrize("exc, status, code", [
    (NotConfigured(f"no connection {LEAK}"), 404, "byoai_not_configured"),
    (ProviderTimeout(f"timed out {LEAK}"), 504, "byoai_timeout"),
    (ByoaiUnreachable(f"cannot reach {LEAK}"), 503, "byoai_unreachable"),
])
def test_byoai_failures_answer_a_code_not_the_text(exc, status, code):
    caught = _raise(exc)
    assert caught.status_code == status
    assert caught.detail["code"] == code and LEAK not in str(caught.detail)
    assert any(LEAK in str(e.get("error")) for e in caught.events if e.get("code") == code)


def test_provider_body_goes_to_the_log_and_the_status_stays_a_field():
    caught = _raise(ProviderHTTPError(401, f"bad key {LEAK}"))
    assert caught.detail["code"] == "byoai_provider_error" and caught.detail["provider_status"] == 401
    assert LEAK not in str(caught.detail)
    assert any(e.get("provider_body") == f"bad key {LEAK}" for e in caught.events)

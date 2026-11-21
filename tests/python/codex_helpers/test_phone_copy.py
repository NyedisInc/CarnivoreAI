
from __future__ import annotations

from datetime import datetime, timezone

from src.core.codex_helpers import alerts
from src.core.codex_helpers import constants as K
from src.core.codex_helpers.check import HelperCheck
from src.core.codex_helpers.handshake import HandshakeResult
from src.core.codex_helpers.quarantine import HelperFlag
from src.core.notifications import copy
from src.core.notifications.kind_specs import get_kind
from src.core.notifications.sources import alerts as alert_source


def _row(verdict: str) -> dict:
    flags = [HelperFlag(K.HOST_NAME, "/x/" + K.HOST_NAME, "0381" if verdict == K.BLOCKED else "03c1",
                        verdict != K.BLOCKED)]
    check = HelperCheck(identity=("/x/codex/0.170.0/bin/codex", 1, 1), binary="/x/codex/0.170.0/bin/codex",
                        version="0.170.0", verdict=verdict, helpers=flags,
                        handshake=HandshakeResult(K.HS_TIMEOUT, 5000), checked_at=datetime.now(timezone.utc))
    return {"id": 9, "key": alerts.alert_key(check), "severity": "error", "params": alerts.params_for(check)}


def test_the_phone_push_names_the_version_and_the_fix():
    rendered = copy.render(alert_source.event_for(_row(K.BLOCKED)), get_kind("apns"), details_on=False)
    assert rendered.type_id == "alert.self_check"
    assert rendered.body.startswith("macos blocked codex 0.170 helpers")
    assert "approve them in system settings > privacy & security" in rendered.body
    assert "codex" in rendered.title


def test_a_host_failure_push_names_the_version_too():
    rendered = copy.render(alert_source.event_for(_row(K.HOST_FAILED)), get_kind("apns"), details_on=False)
    assert "codex 0.170" in rendered.body and "time out" in rendered.body


def test_an_alert_without_its_own_wording_keeps_the_type_copy():
    row = {"id": 3, "key": "self_check.tmux", "severity": "error", "params": {"summary": "x", "findings": "y"}}
    rendered = copy.render(alert_source.event_for(row), get_kind("apns"), details_on=False)
    assert rendered.title == "self check failed"

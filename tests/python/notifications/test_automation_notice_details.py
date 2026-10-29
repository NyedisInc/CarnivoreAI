
from __future__ import annotations

from src.core.notifications import copy
from src.core.notifications.kind_specs import get_kind
from src.core.notifications.sources import alerts

TOKEN = "ghp_" + "a1B2" * 9


def _row(key: str = "automation.notice.abc", text: str = "") -> dict:
    return {"id": 7, "key": key, "severity": "info", "params": {"text": text}}


def test_notice_text_is_details_only_where_allowed_and_scrubbed() -> None:
    event = alerts.event_for(_row(text=f"backups done {TOKEN}"))
    on = copy.render(event, get_kind("slack"), details_on=True)
    assert on.details and "backups done" in on.details and TOKEN not in on.details
    off = copy.render(event, get_kind("slack"), details_on=False)
    assert off.details is None and "backups" not in off.title + off.body
    sms = copy.render(event, get_kind("sns"), details_on=True)
    assert sms.details is None and "backups" not in copy.sms_text(sms)
    other = alerts.event_for(_row(key="automation.report.run_1", text="x"))
    assert other.details is None

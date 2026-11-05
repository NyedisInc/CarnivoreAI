from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

import src.config  # noqa: F401
from src.core.automations import command_allowlist, models as m, notify_policy, timer_status
from src.core.automations.run_title import build
from src.core.automations.targets import command
from src.core.provider_ledger import refresh_poke


class _Spy:

    def __init__(self) -> None:
        self.calls: List[dict] = []

    def raise_alert(self, key: str, **kw: Any) -> object:
        self.calls.append({"key": key, **kw})
        return object()


@pytest.fixture
def spy(monkeypatch) -> _Spy:
    fake = _Spy()
    monkeypatch.setattr(notify_policy.alert_service, "raise_alert", fake.raise_alert)
    return fake


def _run(monkeypatch, exit_code: int, target_extra: Optional[dict] = None, delivery: Optional[dict] = None) -> m.RunOutcome:
    async def fake_child(argv, env, *, on_line, timeout, cwd=None, on_started=None, stdin=None):
        on_line(b"\n")
        on_line(b"3 new urgent alerts\n")
        on_line(b"second line\n")
        return refresh_poke.StreamResult(True, exit_code, False, False, 0.2)

    monkeypatch.setattr(command_allowlist, "allows", lambda text, path=None: True)
    monkeypatch.setattr(command_allowlist, "argv_of", lambda text: ["/bin/check"])
    monkeypatch.setattr(refresh_poke, "run_child_streaming", fake_child)
    store = SimpleNamespace(attachments_root=__import__("pathlib").Path("/nonexistent-never-written"),
                            update_run=lambda *a, **k: None)
    monkeypatch.setattr(command.attachments, "prepare", lambda root, run_id: "/tmp/never")
    automation = {"name": "urgent alert check", "delivery": delivery or {"notify": True, "notify_on": None},
                  "target": {"kind": "command", "command": "check", **(target_extra or {})}}
    return asyncio.run(command.run(SimpleNamespace(store=store), automation, {"run_id": "run_1"}))


def test_exit_zero_succeeds(monkeypatch, spy):
    assert _run(monkeypatch, 0, {"alert_exit_codes": [10]}).status == m.SUCCEEDED
    assert spy.calls == []


def test_listed_code_is_alerted_and_raises_one_warn_alert(monkeypatch, spy):
    out = _run(monkeypatch, 10, {"alert_exit_codes": [10, 11]})
    assert out.status == m.ALERTED and out.reason == "exit_10"
    [call] = spy.calls
    assert call["severity"] == "warn" and call["title_key"] == "app_alert.automation.alerted.title"
    assert call["params"] == {"automation": "urgent alert check", "code": "10", "detail": "3 new urgent alerts"}
    assert call["key"] == "automation.failed.run_1"


def test_unlisted_nonzero_stays_failed(monkeypatch, spy):
    out = _run(monkeypatch, 3, {"alert_exit_codes": [10, 11]})
    assert out.status == m.FAILED and out.reason == "exit_3"
    [call] = spy.calls
    assert call["key"] == "automation.failed.run_1" and call["title_key"] == "app_alert.automation.failed.title"


def test_no_list_behaves_as_today(monkeypatch, spy):
    out = _run(monkeypatch, 10)
    assert out.status == m.FAILED and out.reason == "exit_10"
    assert [c["key"] for c in spy.calls] == ["automation.failed.run_1"]


def test_notify_off_silences_an_alerted_run(monkeypatch, spy):
    out = _run(monkeypatch, 10, {"alert_exit_codes": [10]}, {"notify": False, "notify_on": None})
    assert out.status == m.ALERTED and spy.calls == []


def test_validation():
    ok = m.validate_target({"kind": "command", "command": "x", "alert_exit_codes": [11, 10, 11]})
    assert ok["alert_exit_codes"] == [11, 10]
    assert "alert_exit_codes" not in m.validate_target({"kind": "command", "command": "x", "alert_exit_codes": []})
    assert "alert_exit_codes" not in m.validate_target({"kind": "command", "command": "x"})
    for bad in ([0], [256], [-1], ["10"], [True], [1.5], list(range(1, m.MAX_ALERT_EXIT_CODES + 2)), "10"):
        with pytest.raises(m.AutomationInvalid) as exc:
            m.validate_target({"kind": "command", "command": "x", "alert_exit_codes": bad})
        assert exc.value.code == "target_invalid"
    step = {"kind": "command", "command": "x", "alert_exit_codes": [10]}
    with pytest.raises(m.AutomationInvalid):
        m.validate_target({"kind": "sequence", "steps": [step, {"kind": "command", "command": "y"}]})


def test_title_and_summary():
    report = {"stdout_tail": "\n3 new urgent alerts\nmore\n", "exit_code": 10}
    assert build(name="urgent", status=m.ALERTED, kind="command", reason="exit_10", report=report) == (
        "urgent raised an alert (code 10)", "3 new urgent alerts")
    assert build(name="urgent", status=m.ALERTED, kind="command", reason="exit_10", report={"stdout_tail": ""})[1] == \
        "the command exited with code 10"


def test_timer_status_is_warning_not_error():
    assert timer_status.automation_state({"retry_due_at": None}, {"status": m.ALERTED}) == timer_status.WARNING

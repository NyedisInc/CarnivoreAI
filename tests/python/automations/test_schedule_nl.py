from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_nl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_nl_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import src.config  # noqa: E402,F401
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import automation_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.byoai import gateway as gateway_module  # noqa: E402
from src.core.byoai.contracts import NotConfigured  # noqa: E402
from src.core.timers.cron import CronParseError, next_fire, parse_cron  # noqa: E402

ZONE = "America/New_York"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TZ", ZONE)
    time.tzset()
    app = FastAPI()
    app.include_router(automation_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    box = SimpleNamespace(reply="", error=None, prompts=[])

    async def chat(ref, prompt, **options):
        box.prompts.append((ref, prompt, options.get("system")))
        if box.error:
            raise box.error
        return SimpleNamespace(text=box.reply)

    monkeypatch.setattr(gateway_module, "get_gateway", lambda: SimpleNamespace(chat=chat))
    yield SimpleNamespace(http=TestClient(app), box=box)
    monkeypatch.undo()
    time.tzset()


def _ask(client, text="every third tuesday at 5 pm"):
    return client.http.post("/automations/schedule/parse", json={"text": text, "timezone": ZONE}).json()


def test_third_tuesday_at_5pm_fires_only_on_third_tuesdays(client):
    client.box.reply = '```json\n{"cron": "0 17 * * 2#3", "explain": "the third tuesday of each month at 5 pm"}\n```'
    body = _ask(client)
    assert body["ok"] is True and body["cron"] == "0 17 * * 2#3" and body["explain"]
    assert len(body["fires"]) == 5
    for fire in body["fires"]:
        local = datetime.fromisoformat(fire["in_zone"])
        assert (local.weekday(), (local.day - 1) // 7 + 1, local.hour, local.minute) == (1, 3, 17, 0)
        assert datetime.fromisoformat(fire["utc"]).astimezone(ZoneInfo(ZONE)) == local
    ref, prompt, _system = client.box.prompts[0]
    assert ref == "automations.schedule" and "every third tuesday" in prompt and ZONE in prompt


def test_refusals_are_plain_and_nothing_is_saved(client):
    client.box.reply = '{"cron": "*/5 * * * *", "explain": "x"}'
    assert _ask(client)["reason"] == "interval_under_15_min"
    client.box.reply = '{"cron": "0 17 * * 2L", "explain": "x"}'
    assert _ask(client)["reason"] == "cron_invalid"
    client.box.reply = "no idea"
    assert _ask(client)["reason"] == "ai_output_invalid"
    client.box.reply = '{"refuse": "that needs the last friday"}'
    refused = _ask(client)
    assert refused["ok"] is False and refused["message"] == "that needs the last friday"
    client.box.error = NotConfigured("no model")
    none = _ask(client)
    assert none["ok"] is False and none["reason"] == "no_ai_connection" and none["message"]
    bad_zone = client.http.post("/automations/schedule/parse", json={"text": "x", "timezone": "Nowhere/Land"}).json()
    assert bad_zone["reason"] == "timezone_invalid"
    assert not hasattr(client.http.app.state, "automation_store")


def test_nth_weekday_field_is_additive_and_only_in_day_of_week():
    after = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    assert parse_cron("0 17 * * 2#3").nth_weekdays == {(2, 3)}
    assert parse_cron("0 17 * * tue#1,fri").weekdays == {5}
    old = parse_cron("30 9 * * 1-5")
    assert old.weekdays == {1, 2, 3, 4, 5} and old.nth_weekdays == frozenset()
    assert next_fire(old, after).astimezone().weekday() < 5
    for bad in ("0 17 2#3 * *", "0 17 * 2#3 *", "2#3 17 * * *", "0 17 * * 2#6", "0 17 * * 2#0", "0 17 * * 1-2#3", "0 17 * * *#3"):
        with pytest.raises(CronParseError):
            parse_cron(bad)

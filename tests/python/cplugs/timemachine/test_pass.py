
from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.config  # noqa: F401
from src.api.auth import require_auth
from src.core.app_alerts import constants as AK
from src.core.app_alerts import service as alerts
from src.core.db import db_path_for
from src.core.db_migration import ensure_db_migrated
from src.cplugs.host import capabilities, routes as host_routes, runtime
from src.cplugs.sdk import CapabilityMissing, context as sdk_context
from src.cplugs.timemachine import CPLUG, checks, scheduler, service
from src.cplugs.timemachine import constants as K
from tests.python.cplugs.owner import turn_on

NOW = 2_000_000_000.0
KEY = "cplug.timemachine.time_machine"


@pytest.fixture()
def db(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    path = db_path_for(state)
    alerts.configure(path, None)
    service.reset()
    yield path
    alerts.configure(None, None)
    service.reset()


class Ctx:

    def __init__(self, granted=True, on=True):
        self.on = on
        self.granted = granted
        if granted:
            self.alert = capabilities.alerter("timemachine")
            self.alert_resolve = capabilities.alert_resolver("timemachine")

    def enabled_now(self):
        return self.on

    def has(self, permission):
        return self.granted and permission == "notify"


def _out(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(["tmutil"], returncode, stdout=stdout, stderr=stderr)


def _timeout(*_a):
    raise subprocess.TimeoutExpired("tmutil", 15)


def _fake(monkeypatch, latest=None, destinations=None, status=None):
    table = {"latestbackup": latest, "destinationinfo": destinations, "status": status}

    def fake(verb):
        answer = table[verb]
        if answer is None:
            return _out(returncode=1)
        if callable(answer):
            return answer()
        return answer

    monkeypatch.setattr(checks, "tmutil", fake)


def _at(age_hours):
    taken = datetime.fromtimestamp(NOW) - timedelta(hours=age_hours)
    return _out(f"/Volumes/TM/Backups.backupdb/mac/{taken:%Y-%m-%d-%H%M%S}.backup\n")


def _active(db):
    return {r["key"]: r for r in alerts.list_view(db, include_closed=False, limit=100)["alerts"] if r["state"] == AK.STATE_ACTIVE}


def _pass(ctx):
    return service.run_pass(ctx, now=NOW)


def test_stale_raises_at_once_with_one_recheck_action_and_fresh_resolves(db, monkeypatch):
    ctx = Ctx()
    _fake(monkeypatch, latest=_at(K.TIME_MACHINE_MAX_AGE_HOURS + 5))
    assert _pass(ctx) == {"state": "firing", "outcome": "raised"}
    row = _active(db)[KEY]
    assert row["title_key"] == K.TITLE_STALE and row["source"] == "cplug.timemachine" and row["params"]["hours"] == 29
    recheck = [a for a in row["actions"] if a["id"] == "recheck"]
    assert len(recheck) == 1 and recheck[0]["route"] == "/cplugs/timemachine/check"
    _fake(monkeypatch, latest=_at(1))
    assert _pass(ctx)["outcome"] == "resolved" and KEY not in _active(db)
    assert _pass(ctx)["outcome"] == "quiet"


def test_unknown_is_kept_once_then_raises_with_the_explainer_and_clears(db, monkeypatch):
    ctx = Ctx()
    _fake(monkeypatch, latest=_timeout)
    assert _pass(ctx)["outcome"] == "kept" and KEY not in _active(db)
    assert _pass(ctx) == {"state": "unknown", "reason": "unreadable", "outcome": "raised"}
    row = _active(db)[KEY]
    assert row["title_key"] == K.TITLE_UNKNOWN and row["detail_key"] == K.DETAIL_UNKNOWN_BY_REASON["unreadable"]
    explainer = next(a for a in row["actions"] if a["id"] == "check_access")
    assert explainer["explain_key"] == K.EXPLAIN_BY_REASON["unreadable"]
    assert [a["id"] for a in explainer["actions"]] == ["open_privacy", "recheck"]
    _fake(monkeypatch, latest=_at(1))
    assert _pass(ctx)["outcome"] == "resolved" and KEY not in _active(db)
    _fake(monkeypatch, latest=_timeout)
    assert _pass(ctx)["outcome"] == "kept" and KEY not in _active(db)


def test_a_firing_pass_resets_the_unknown_count(db, monkeypatch):
    ctx = Ctx()
    _fake(monkeypatch, latest=_timeout)
    assert _pass(ctx)["outcome"] == "kept"
    _fake(monkeypatch, latest=_at(K.TIME_MACHINE_MAX_AGE_HOURS + 5))
    assert _pass(ctx)["outcome"] == "raised"
    _fake(monkeypatch, latest=_timeout)
    assert _pass(ctx)["outcome"] == "kept"


def test_stop_and_reset_do_not_wait_on_a_pass_in_flight(db):
    import threading
    import time

    ctx = Ctx()
    ctx.on = False
    held = threading.Event()

    def hold():
        with service._LOCK:
            held.set()
            time.sleep(1.5)

    t = threading.Thread(target=hold)
    t.start()
    held.wait()
    began = time.monotonic()
    asyncio.run(CPLUG.on_stop(ctx))
    service.reset()
    waited = time.monotonic() - began
    t.join()
    assert waited < 0.5


@pytest.mark.parametrize("said,reason", [
    ("tmutil: latestbackup requires Full Disk Access privileges.", "access"),
    ("something odd", "unreadable"),
    ("tmutil: No machine directory found for host.", "unreadable"),
])
def test_unreadable_says_why_and_the_reason_picks_the_keys(db, monkeypatch, said, reason):
    ctx = Ctx()
    _fake(monkeypatch, latest=_out(stderr=said, returncode=1), destinations=_out("Name : TimeMachine\n"))
    _pass(ctx)
    assert _pass(ctx)["reason"] == reason
    assert _active(db)[KEY]["detail_key"] == K.DETAIL_UNKNOWN_BY_REASON[reason]


def test_a_running_backup_neither_raises_nor_resolves(db, monkeypatch):
    ctx = Ctx()
    _fake(monkeypatch, latest=_timeout, status=_out("    Running = 1;\n"))
    for _ in range(K.TM_UNKNOWN_PASSES_TO_ALERT + 1):
        assert _pass(ctx) == {"state": "busy", "outcome": "kept"}
    assert KEY not in _active(db)
    _fake(monkeypatch, latest=_timeout, status=_out("    Running = 0;\n"))
    assert checks.check_time_machine(NOW).state == checks.UNKNOWN


def test_a_busy_pass_resets_the_unknown_count(db, monkeypatch):
    ctx = Ctx()
    _fake(monkeypatch, latest=_timeout)
    assert _pass(ctx)["outcome"] == "kept"
    _fake(monkeypatch, latest=_timeout, status=_out("    Running = 1;\n"))
    assert _pass(ctx) == {"state": "busy", "outcome": "kept"}
    _fake(monkeypatch, latest=_timeout)
    assert _pass(ctx)["outcome"] == "kept" and KEY not in _active(db)


@pytest.mark.parametrize("said,destinations", [
    ("tmutil: No machine directory found for host.", _out("tmutil: No destinations configured.\n")),
    ("tmutil: No destinations configured.", None),
    ("something odd", _out("No destinations configured.\n")),
])
def test_no_destination_is_off_and_closes_its_alert(db, monkeypatch, said, destinations):
    ctx = Ctx()
    _fake(monkeypatch, latest=_out(stderr=said, returncode=1), destinations=destinations)
    assert checks.check_time_machine(NOW) is None
    _fake(monkeypatch, latest=_timeout)
    _pass(ctx)
    _pass(ctx)
    assert KEY in _active(db)
    _fake(monkeypatch, latest=_out(stderr="tmutil: No destinations configured.", returncode=1))
    assert _pass(ctx) == {"state": "none", "outcome": "resolved"} and KEY not in _active(db)
    _fake(monkeypatch, latest=_timeout)
    assert _pass(ctx)["outcome"] == "kept"


def test_a_leftover_alert_closes_on_the_first_pass_after_a_restart(db, monkeypatch):
    capabilities.alerter("timemachine")(K.ALERT_KEY, "warn", K.TITLE_STALE, {"hours": 30, "max_hours": 24}, detail_key=K.DETAIL_STALE)
    assert KEY in _active(db)
    _fake(monkeypatch, latest=_at(1))
    assert _pass(Ctx())["outcome"] == "resolved" and KEY not in _active(db)


def test_off_and_missing_grant_apply_nothing(db, monkeypatch):
    _fake(monkeypatch, latest=_at(K.TIME_MACHINE_MAX_AGE_HOURS + 5))
    assert _pass(Ctx(on=False)) == {"state": "firing", "outcome": "off"}
    assert _pass(Ctx(granted=False)) == {"state": "firing", "outcome": "not_granted"}
    assert KEY not in _active(db)


def test_start_without_notify_starts_no_loop_and_stop_without_resolve_does_not_raise(db):
    ctx = Ctx(granted=False)
    asyncio.run(CPLUG.on_start(ctx))
    assert scheduler._task is None
    ctx.on = False
    asyncio.run(CPLUG.on_stop(ctx))


def test_stop_by_the_owner_resolves_the_alert_but_shutdown_leaves_it(db, monkeypatch):
    ctx = Ctx()
    _fake(monkeypatch, latest=_at(K.TIME_MACHINE_MAX_AGE_HOURS + 5))
    _pass(ctx)
    asyncio.run(CPLUG.on_stop(ctx))
    assert KEY in _active(db)
    ctx.on = False
    asyncio.run(CPLUG.on_stop(ctx))
    assert KEY not in _active(db)


def test_a_failed_pass_does_not_end_the_loop(monkeypatch):
    runs = []

    def flaky(_ctx):
        runs.append(1)
        if len(runs) == 1:
            raise CapabilityMissing("revoked")

    monkeypatch.setattr(service, "run_pass", flaky)
    monkeypatch.setattr(K, "FIRST_PASS_DELAY_S", 0)
    monkeypatch.setattr(K, "PERIOD_S", 0.01)

    async def go():
        scheduler.start(Ctx())
        for _ in range(100):
            if len(runs) >= 2:
                break
            await asyncio.sleep(0.01)
        await scheduler.stop()

    with structlog.testing.capture_logs() as logs:
        asyncio.run(go())
    assert len(runs) >= 2 and any(e["event"] == "timemachine_pass_failed" for e in logs)
    assert scheduler._task is None


def test_post_check_runs_one_pass_and_answers_409_while_off(db, monkeypatch, tmp_path):
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    taken = datetime.now() - timedelta(hours=K.TIME_MACHINE_MAX_AGE_HOURS + 5)
    _fake(monkeypatch, latest=_out(f"/Volumes/TM/Backups.backupdb/mac/{taken:%Y-%m-%d-%H%M%S}.backup\n"))
    with TestClient(app) as client:
        off = client.post("/api/v1/cplugs/timemachine/check")
        assert off.status_code == 409 and off.json()["detail"]["code"] == "cplug_disabled"
        turn_on(host, "timemachine")
        done = client.post("/api/v1/cplugs/timemachine/check")
        assert done.status_code == 200, done.text
        assert done.json() == {"state": "firing", "outcome": "raised"}
    assert KEY in _active(db)


def test_the_wiring_the_plugin_depends_on():
    assert runtime._AUDIT_PERMISSION["alert_resolve"] == sdk_context.CAPABILITY_GRANTS["alert_resolve"] == "notify"
    assert CPLUG.manifest.id == "timemachine" and CPLUG.manifest.default_enabled is False

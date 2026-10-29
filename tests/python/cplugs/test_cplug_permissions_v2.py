
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import activity_log, capabilities, consent, risk, routes as host_routes, runtime, session_fields
from src.cplugs.sdk import permission_registry as registry
from src.cplugs.host import mcp as host_mcp, state as owner_state
from src.cplugs.sdk.definition import CplugDefinition
from src.cplugs.sdk.manifest import parse_manifest
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from tests.python.cplugs.owner import turn_on

REASONS = {"sessions.read": "lists your sessions", "sessions.message": "types a line into a session you pick",
           "feed.view: raw": "reads transcripts", "network_hosts.write:api.example.com": "posts a summary",
           "network_hosts:api.example.com": "reads the api"}
DIGEST = "d1" * 32


def raw_manifest(perms, reasons=None):
    raw = {
        "schema": 1, "id": "tpdemo", "name_key": "cplug.tpdemo.name", "description_key": "cplug.tpdemo.description",
        "version": "1.0.0", "icon": "list", "author": "test", "min_app_version": "1.12.20", "tier": "builtin",
        "default_enabled": False, "surfaces": {}, "settings_schema": {"version": 1, "fields": {}},
        "permissions": {"app": perms}, "permission_reasons": {k: v for k, v in (REASONS if reasons is None else reasons).items() if k in perms},
    }
    if any(p.startswith("network_hosts") for p in perms):
        raw["network_hosts"] = [{"host": "api.example.com", "reason": "reads the api", "methods": ["GET", "POST"]}]
    return raw


def third_party(perms=("sessions.read", "sessions.message", "network_hosts:api.example.com",
                       "network_hosts.write:api.example.com"), reasons=None):
    return replace(parse_manifest(raw_manifest(list(perms), reasons)), tier="thirdparty", code_digest=DIGEST)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    m = third_party()
    d = CplugDefinition(manifest=m)
    real_find = runtime.find
    monkeypatch.setattr(runtime, "find", lambda cid: d if cid == "tpdemo" else real_find(cid))
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        yield SimpleNamespace(m=m, client=client, host=host, app=app, tmp=tmp_path)


def put(rig, body, cid="tpdemo"):
    return rig.client.put(f"/api/v1/cplugs/{cid}", json=body)


def echo(rig, grants, ticks):
    sheet = rig.client.get("/api/v1/cplugs/tpdemo/sheet").json()
    return {"digest": sheet["digest"], "body_sha": sheet["body_sha"], "grants_sha": consent.grants_sha(grants), "ticks": ticks}



def test_risk_tiers_and_combined_warnings():
    assert [registry.risk_of(p) for p in ("sessions.read", "notify", "network_hosts:a.com", "sessions.message", "lan_hosts:http://nas.local:80")] \
        == ["low", "low", "medium", "high", "high"]
    assert registry.risk_of("swarm", "thirdparty") == "never" and registry.risk_of("swarm") == "high"
    assert registry.risk_of("made.up", "thirdparty") == "never" and registry.risk_of("made.up") == "high"
    both = ("feed.view: raw", "network_hosts.write:api.github.com")
    assert risk.warnings_for(both) == [{"code": "sends_transcripts", "reads": "feed.view: raw", "host": "api.github.com"}]
    assert risk.warnings_for(("feed.view: raw", "network_hosts:api.github.com")) == []
    assert risk.warnings_for(("network_hosts.write:api.github.com",)) == []



def test_sessions_read_returns_only_the_allow_listed_fields():
    session = SimpleNamespace(id="ses_1", created_at=datetime(2026, 10, 1), last_activity=datetime(2026, 10, 2),
                              working_dir="/Users/x/secret", pty_pid=7)
    info = SimpleNamespace(session=session, session_row_id=9, label="work", project_id=3, activity_status="idle", unread=False,
                           startup_gate="ready", agent_family="claude", working_on="refactoring the vault", parked_summary="s",
                           recent_logs=["terminal output"], account_id="acct", tmux_session="cloude_x")
    row = session_fields.project(info)
    assert tuple(row) == session_fields.FIELDS == ("id", "created_at", "last_activity", "session_row_id", "label", "project_id",
                                                   "activity_status", "unread", "startup_gate", "agent_family")
    assert row["id"] == "ses_1" and row["last_activity"] == "2026-10-02T00:00:00"
    assert "/Users/x/secret" not in json.dumps(row) and "refactoring" not in json.dumps(row)

    async def infos():
        return [info]

    sessions = capabilities.Sessions(infos)
    assert asyncio.run(sessions.list_allowed()) == [row] and asyncio.run(sessions.get_allowed("ses_1")) == row
    with pytest.raises(PermissionError):
        asyncio.run(sessions.get_allowed("remote:peer-1:ses_1"))



def test_a_third_party_plugin_cannot_be_enabled_or_granted_without_the_sheet(rig):
    asked = list(rig.m.permissions)
    card = rig.client.get("/api/v1/cplugs/tpdemo").json()
    assert card["consent_required"] is True and card["risks"]["sessions.message"] == "high" and card["revision"] == 0
    sheet = rig.client.get("/api/v1/cplugs/tpdemo/sheet").json()
    assert [p["needs_tick"] for p in sheet["permissions"]] == [False, True, True, True]
    assert all(p["granted"] is False for p in sheet["permissions"]) and sheet["digest"] == DIGEST

    refused = lambda body, code, status=422: (  # noqa: E731
        (r := put(rig, body)).status_code == status and r.json()["detail"]["code"] == code)
    base = {"revision": 0, "enabled": True, "grants": {"app": asked}}
    assert refused(base, "consent_required")
    assert refused({**base, "consent": echo(rig, asked, [])}, "tick_missing")
    assert refused({**base, "consent": echo(rig, asked, ["sessions.message"])}, "tick_missing")
    assert refused({**base, "consent": {**echo(rig, asked, asked), "grants_sha": consent.grants_sha(asked[:2])}}, "consent_mismatch")
    assert refused({**base, "consent": {**echo(rig, asked, asked), "body_sha": "0" * 64}}, "consent_stale", 409)
    assert refused({**base, "consent": {**echo(rig, asked, asked), "digest": "e" * 64}}, "consent_stale", 409)
    assert refused({"revision": 0, "grants": {"app": ["sessions.read", "agent_writes"]}}, "grant_not_asked")
    assert owner_state.get(rig.tmp, rig.m).enabled is False

    ok = put(rig, {**base, "consent": echo(rig, asked, asked[1:])})
    assert ok.status_code == 200 and ok.json()["enabled"] is True and ok.json()["grants"]["app"] == asked
    assert owner_state.get(rig.tmp, rig.m).digest == DIGEST

    assert put(rig, {"revision": 1, "grants": {"app": asked[:1]}}).status_code == 200
    assert put(rig, {"revision": 2, "enabled": False}).status_code == 200
    assert refused({"revision": 3, "enabled": True}, "consent_required")
    assert refused({"revision": 3, "grants": {"app": asked}, "consent": echo(rig, asked, [])}, "tick_missing")


def test_never_and_unexplained_permissions_and_the_first_party_control(rig, monkeypatch):
    swarm = replace(third_party(("sessions.read", "swarm")), permission_reasons={"sessions.read": "r", "swarm": "p"})
    monkeypatch.setattr(runtime, "find", lambda cid: CplugDefinition(manifest=swarm) if cid == "tpdemo" else None)
    body = {"revision": 0, "enabled": True, "grants": {"app": ["sessions.read", "swarm"]}}
    assert put(rig, body).json()["detail"]["code"] == "grant_never"

    silent = third_party(("sessions.read",), reasons={})
    monkeypatch.setattr(runtime, "find", lambda cid: CplugDefinition(manifest=silent) if cid == "tpdemo" else None)
    sheet = rig.client.get("/api/v1/cplugs/tpdemo/sheet").json()
    consent_body = {"digest": sheet["digest"], "body_sha": sheet["body_sha"], "grants_sha": consent.grants_sha(["sessions.read"]), "ticks": []}
    r = put(rig, {"revision": 0, "enabled": True, "grants": {"app": ["sessions.read"]}, "consent": consent_body})
    assert r.json()["detail"]["code"] == "reason_missing"

    monkeypatch.undo()
    assert put(rig, {"revision": 0, "enabled": True, "grants": {"app": ["sessions.read"]}}, "huddle").status_code == 200
    assert rig.client.get("/api/v1/cplugs/huddle/sheet").json()["consent_required"] is False



def test_mcp_cplug_update_is_limited_to_disable_and_revoke(tmp_path, monkeypatch):
    from src.core.mcp import write_tools

    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    parked = []

    async def park(manager, caller, target_id, target_tmux, name, summary, shown, run, dedupe_key="", beast_eligible=True):
        parked.append(summary)
        return {"content": [{"type": "text", "text": json.dumps({"status": "pending"})}]}

    monkeypatch.setattr(write_tools, "park", park)
    manager = SimpleNamespace(app=app, gate_waited=True)
    pane = AgentCaller("ses_1", "cloude_a", "ses_1")

    def call(args):
        result = asyncio.run(tools.call_tool(manager, pane, "cplug_update", {"cplug_id": "huddle", "revision": 0, **args}))
        return not result.get("isError"), result["content"][0]["text"]

    granted = list(owner_state.get(host.state_dir, runtime.find("huddle").manifest).grants)
    for refused in ({"enabled": True}, {"settings": {"k": 1}}, {"grants": {"app": granted + ["made.up"]}},
                    {"consent": {}}, {}, {"enabled": False, "settings": {"k": 1}}):
        ok, text = call(refused)
        assert not ok and "cplug_update" in text, refused
    assert parked == []
    assert call({"enabled": False})[0] and call({"grants": {"app": granted[:1]}})[0] and len(parked) == 2
    assert "settings" not in host_mcp.HOST_WRITES["cplug_update"][1]



def test_every_capability_call_lands_in_the_activity_log(rig):
    host = rig.host
    turn_on(host)
    asked = {"n": 0}

    async def infos():
        asked["n"] += 1
        return []

    ctx = host.context("huddle", infos=infos)
    assert type(ctx.sessions).__mro__[1] is capabilities.Sessions
    assert asyncio.run(ctx.sessions.list()) == [] and asyncio.run(ctx.sessions.list()) == [] and asked["n"] == 2
    assert ctx.toast("ses_abc123", "fixed title") is None
    ctx.toast("not an id; a line of text", "t")
    with pytest.raises(AttributeError):
        ctx.sessions.nonesuch

    log = activity_log.ActivityLog(rig.tmp)
    rows = log.recent("huddle")
    by_method = {(r["method"], r["target"]): r for r in rows}
    assert by_method[("sessions.list", "")]["count"] == 2 and by_method[("sessions.list", "")]["permission"] == "sessions.read"
    assert ("toast", "ses_abc123") in by_method and by_method[("toast", "ses_abc123")]["permission"] == "notify"
    assert ("toast", "") in by_method
    assert "fixed title" not in json.dumps(rows) and "a line of text" not in json.dumps(rows)

    async def boom():
        raise RuntimeError("secret detail")

    ctx2 = host.context("huddle", infos=boom)
    with pytest.raises(RuntimeError):
        asyncio.run(ctx2.sessions.list())
    assert log.recent("huddle", 1)[0]["status"] == "error:RuntimeError" and "secret detail" not in json.dumps(log.recent("huddle"))

    got = rig.client.get("/api/v1/cplugs/huddle/activity").json()["activity"]
    assert got[0]["status"] == "error:RuntimeError" and len(got) == len(log.recent("huddle"))
    assert rig.client.get("/api/v1/cplugs/nonesuch/activity").status_code == 404
    rig.app.dependency_overrides.clear()
    assert rig.client.get("/api/v1/cplugs/huddle/activity").status_code == 401


def test_a_third_party_toast_carries_the_plugin_id_and_is_capped(monkeypatch):
    from src.core import session_change_notice
    from src.core.attention import raise_gate
    import src.models as models

    titles = []
    manager = SimpleNamespace(_notification_policy_store=object(), notification_policy_stamp=lambda sid: None,
                              record_toast=lambda **kw: titles.append(kw["title"]) or SimpleNamespace(session_id="s", id="t"))
    monkeypatch.setattr(raise_gate, "resolve_raise", lambda *a, **k: SimpleNamespace(raises_toast=True))
    monkeypatch.setattr(session_change_notice, "publish", lambda *a, **k: None)
    monkeypatch.setattr(models, "ToastNewMessage", lambda toast: SimpleNamespace(model_dump_json=lambda: "{}"))
    state = SimpleNamespace(session_manager=manager)
    capabilities.toaster("tpdemo", state, "tpdemo: ")("ses_1", "Your key was revoked " + "x" * 300)
    capabilities.toaster("huddle", state)("ses_1", "plain")
    assert titles[0].startswith("tpdemo: Your key") and len(titles[0]) == 80 and titles[1] == "plain"



@pytest.fixture
def grant_tp(rig):
    def grant(*grants, digest=DIGEST):
        return owner_state.update(rig.tmp, rig.m, None, lambda st: replace(st, enabled=True, grants=tuple(grants), digest=digest))
    return grant


def test_a_third_party_alert_is_namespaced_and_cannot_reach_a_host_string(monkeypatch):
    from src.core.app_alerts import service

    raised = []
    monkeypatch.setattr(service, "raise_alert", lambda key, **kw: raised.append((key, kw["title_key"])) or {})
    outside, inside = capabilities.alerter("tpdemo", True), capabilities.alerter("huddle")
    for key in ("integrity", "Integrity", "a.b", "x" * 33, ""):
        if key == "integrity":
            outside(key, "warning", "cplug.tpdemo.alert")
            continue
        with pytest.raises(ValueError):
            outside(key, "warning", "cplug.tpdemo.alert")
    for title_key in ("app.alerts.crash_loop", "cplug.other.alert", "cplug.tpdemo"):
        with pytest.raises(ValueError):
            outside("mine", "warning", title_key)
    inside("integrity", "warning", "any.key")
    assert raised == [("cplug.tpdemo.p.integrity", "cplug.tpdemo.alert"), ("cplug.huddle.integrity", "any.key")]


def test_a_third_party_toast_refuses_urls_and_spends_a_budget(monkeypatch):
    from src.core import session_change_notice
    from src.core.attention import raise_gate
    import src.models as models

    titles = []
    manager = SimpleNamespace(_notification_policy_store=object(), notification_policy_stamp=lambda sid: None,
                              record_toast=lambda **kw: titles.append(kw["title"]) or SimpleNamespace(session_id="s", id="t"))
    monkeypatch.setattr(raise_gate, "resolve_raise", lambda *a, **k: SimpleNamespace(raises_toast=True))
    monkeypatch.setattr(session_change_notice, "publish", lambda *a, **k: None)
    monkeypatch.setattr(models, "ToastNewMessage", lambda toast: SimpleNamespace(model_dump_json=lambda: "{}"))
    clock = {"t": 1000.0}
    monkeypatch.setattr(capabilities, "_toast_clock", lambda: clock["t"])
    capabilities._toast_times.clear()
    state = SimpleNamespace(session_manager=manager)
    outside = capabilities.toaster("tpdemo", state, "tpdemo: ")
    for bad in ("see https://evil.example/login", "go to www.evil.example", "visit evil.example now", "ftp://x"):
        assert outside("ses_1", bad) is None
    assert titles == []
    assert all(outside("ses_1", f"note {n}") for n in range(capabilities.TOAST_BUDGET))
    assert outside("ses_1", "one too many") is None and len(titles) == capabilities.TOAST_BUDGET
    clock["t"] += capabilities.TOAST_WINDOW_S + 1
    assert outside("ses_1", "next hour") is not None
    inside = capabilities.toaster("huddle", state)
    assert all(inside("ses_1", "see https://ok.example") for _ in range(10))


def test_a_third_party_context_only_ever_holds_allow_listed_sessions_and_projects(rig, grant_tp, monkeypatch):
    from src.api import projects_service

    grant_tp("sessions.read", "sessions.message")
    session = SimpleNamespace(id="ses_1", created_at=datetime(2026, 10, 1), last_activity=datetime(2026, 10, 2), working_dir="/Users/x/secret")
    info = SimpleNamespace(session=session, session_row_id=9, label="work", project_id=3, activity_status="idle", unread=False,
                           startup_gate="ready", agent_family="claude", working_on="refactoring the vault", parked_summary="s",
                           recent_logs=["terminal output"], account_id="acct")

    async def infos():
        return [info]

    ctx = rig.host.context("tpdemo", infos=infos)
    rows = asyncio.run(ctx.sessions.list())
    assert rows == [session_fields.project(info)] and "/Users/x/secret" not in json.dumps(rows, default=str)
    assert asyncio.run(ctx.sessions.get("ses_1")) == rows[0]
    with pytest.raises(PermissionError):
        asyncio.run(ctx.sessions.get("remote:peer-1:ses_1"))
    with pytest.raises(PermissionError):
        asyncio.run(ctx.sessions.durable_keys())
    monkeypatch.setattr(projects_service, "current_view", lambda *a, **k: None)
    monkeypatch.setattr(projects_service, "views_to_responses", lambda view, cls: [
        SimpleNamespace(id=1, name="p", path="/Users/x/secret", default_launch_profile="d")])
    assert ctx.projects.get(1) == {"id": 1, "name": "p"}
    assert capabilities.Projects().get(1)["path"] == "/Users/x/secret"
    full = rig.host.context("huddle", infos=infos)
    assert asyncio.run(full.sessions.list()) == [info]


def test_start_and_wake_ride_their_own_permissions(rig, grant_tp, monkeypatch):
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    async def infos():
        return []

    grant_tp("sessions.read", "sessions.message")
    ctx = rig.host.context("tpdemo", request=request, infos=infos)
    assert hasattr(ctx.sessions, "message") and not hasattr(ctx.sessions, "wake") and not hasattr(ctx.sessions, "start")
    m = replace(rig.m, permissions=(*rig.m.permissions, "sessions.control", "sessions.create"))
    real_find = runtime.find
    monkeypatch.setattr(runtime, "find", lambda cid: CplugDefinition(manifest=m) if cid == "tpdemo" else real_find(cid))
    grant_tp("sessions.read", "sessions.message", "sessions.control", "sessions.create")
    ctx = rig.host.context("tpdemo", request=request, infos=infos)
    assert hasattr(ctx.sessions, "wake") and hasattr(ctx.sessions, "asleep")
    assert not hasattr(ctx.sessions, "start")
    from src.cplugs.host import audit
    assert [audit.sessions_permission(x) for x in ("list", "message", "start", "wake", "asleep")] \
        == ["sessions.read", "sessions.message", "sessions.create", "sessions.control", "sessions.control"]


def test_a_changed_or_missing_code_digest_drops_every_grant(rig, grant_tp, monkeypatch):
    async def infos():
        return []

    grant_tp("sessions.read")
    assert hasattr(rig.host.context("tpdemo", infos=infos), "sessions")
    moved = replace(rig.m, code_digest="f" * 64)
    real_find = runtime.find
    monkeypatch.setattr(runtime, "find", lambda cid: CplugDefinition(manifest=moved) if cid == "tpdemo" else real_find(cid))
    assert not hasattr(rig.host.context("tpdemo", infos=infos), "sessions") and rig.host._live_grants(moved) == frozenset()
    blank = replace(rig.m, code_digest="")
    asked = list(blank.permissions)
    with pytest.raises(consent.ConsentRefused) as refused:
        consent.check(blank, asked, [], {"digest": "", "body_sha": consent.sheet(blank)["body_sha"],
                                         "grants_sha": consent.grants_sha(asked), "ticks": asked})
    assert refused.value.code == "digest_unknown" and refused.value.status == 409


def test_the_activity_write_happens_off_the_event_loop(tmp_path, monkeypatch):
    import threading
    from src.cplugs.host import audit

    seen = []
    log = activity_log.ActivityLog(tmp_path)
    real = log.record

    def spy(*a, **k):
        try:
            asyncio.get_running_loop()
            seen.append("on_loop")
        except RuntimeError:
            seen.append("off_loop")
        return real(*a, **k)

    monkeypatch.setattr(log, "record", spy)

    class Cap:
        async def look(self):
            return "x"

        def peek(self):
            return "y"

    cap = audit.audited(Cap(), log, "tpdemo", "cap", "sessions.read")
    asyncio.run(cap.look())
    assert seen == ["off_loop"]
    assert cap.peek() == "y" and log.recent("tpdemo")[0]["method"] == "cap.peek" and len(seen) == 2
    seen.clear()

    async def on_loop():
        return cap.peek()

    assert asyncio.run(on_loop()) == "y" and seen == ["on_loop"]
    assert activity_log.HOT_BUSY_S < activity_log.BUSY_S

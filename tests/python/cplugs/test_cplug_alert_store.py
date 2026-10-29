from __future__ import annotations

import pytest

import src.config  # noqa: F401
from src.core.app_alerts import constants as AK
from src.core.app_alerts import service
from src.core.db import db_path_for
from src.core.db_migration import ensure_db_migrated
from src.cplugs.host import capabilities, runtime
from src.cplugs.sdk import context

EXPLAINER = {
    "id": "check_access", "label_key": "cplug.demo.action.check", "explain_key": "cplug.demo.alert.explain",
    "actions": [{"id": "recheck", "label_key": "app_alert.action.recheck", "method": "POST", "route": "/cplugs/demo/check"}],
}


@pytest.fixture()
def db(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    path = db_path_for(state)
    service.configure(path, None)
    yield path
    service.configure(None, None)


def _active(db):
    return {r["key"]: r for r in service.list_view(db, include_closed=False, limit=100)["alerts"] if r["state"] == AK.STATE_ACTIVE}


def test_a_plugin_alert_keeps_its_own_strings_and_actions_and_resolves(db):
    row = capabilities.alerter("demo")("time_machine", "warn", "cplug.demo.alert.title", {"hours": 30},
                                       detail_key="cplug.demo.alert.detail", actions=[EXPLAINER])
    assert row is not None and row["key"] == "cplug.demo.time_machine"
    stored = _active(db)["cplug.demo.time_machine"]
    assert stored["title_key"] == "cplug.demo.alert.title" and stored["detail_key"] == "cplug.demo.alert.detail"
    assert [a["id"] for a in stored["actions"]] == ["check_access", "open_plugins"]
    assert stored["actions"][0]["explain_key"] == "cplug.demo.alert.explain"
    assert stored["actions"][0]["actions"][0]["route"] == "/cplugs/demo/check"
    capabilities.alert_resolver("demo")("time_machine")
    assert _active(db) == {}


def test_the_store_refuses_strings_that_are_not_the_alerts_own(db):
    assert service.raise_alert("backup_health.x", source="backup_health", severity="warn", title_key="cplug.demo.x") is None
    assert service.raise_alert("k", source="cplug.demo\n", severity="warn", title_key="cplug.demo\n.x") is None
    alert = capabilities.alerter("demo")
    assert alert("k", "warn", "cplug.other.alert.title") is None
    assert alert("k", "warn", "cplug.demo.alert.title", detail_key="cplug.other.detail") is None
    foreign = dict(EXPLAINER, label_key="cplug.other.action")
    assert alert("k", "warn", "cplug.demo.alert.title", actions=[foreign]) is None
    assert _active(db) == {}


def test_a_third_party_alert_cannot_carry_actions_or_a_foreign_detail():
    alert = capabilities.alerter("demo", True)
    with pytest.raises(ValueError):
        alert("k", "warn", "cplug.demo.t", actions=[EXPLAINER])
    with pytest.raises(ValueError):
        alert("k", "warn", "cplug.demo.t", detail_key="app_alert.x")
    with pytest.raises(ValueError):
        capabilities.alert_resolver("demo", True)("Bad Key")


def test_alert_resolve_is_wired_into_the_grant_and_audit_tables():
    assert runtime._AUDIT_PERMISSION["alert_resolve"] == context.CAPABILITY_GRANTS["alert_resolve"] == "notify"

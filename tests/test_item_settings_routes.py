
from __future__ import annotations

from contextlib import closing

import pytest

from tests.layouts_helpers import migrated

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.item_settings_routes import router
from src.core import item_catalog, item_settings_schema, session_change_notice
from src.core.db import connect
from src.core.item_catalog import ItemDecl
from src.core.item_settings_schema import parse_schema

API = "/api/v1/item-settings"
LOG = f"{API}/widget/core.activity-log"


def _app(authed: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    if authed:
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return app


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    state_dir = tmp_path / "state"
    db_path = migrated(state_dir)
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state_dir, raising=True)
    frames = []
    monkeypatch.setattr(session_change_notice, "publish", lambda state, frame: frames.append(frame))
    return TestClient(_app(True)), db_path, frames


@pytest.fixture()
def rich_widget(monkeypatch):
    schema = parse_schema({"version": 1, "fields": {
        "wrap": {"kind": "boolean", "labelKey": "t.a", "default": False},
        "rows": {"kind": "number", "labelKey": "t.b", "default": 10, "min": 1, "max": 50},
        "order": {"kind": "enum", "labelKey": "t.c", "default": "new", "options": ["new", "old"]},
        "title": {"kind": "string", "labelKey": "t.d", "default": "", "maxLength": 5},
    }})
    decls = item_catalog.load_widgets() + (
        ItemDecl("widget", "test.rich", True, schema, "singleton"),
    )
    monkeypatch.setattr(item_catalog, "load_widgets", lambda path=None: decls)
    return f"{API}/widget/test.rich"


def test_both_verbs_refuse_a_caller_with_no_credential(env):
    _, db_path, _ = env
    client = TestClient(_app(False))
    assert client.get(API).status_code in (401, 403)
    assert client.get(LOG).status_code in (401, 403)
    assert client.get("/api/v1/widgets").status_code in (401, 403)
    res = client.patch(LOG, json={"values": {"showSystem": False}})
    assert res.status_code in (401, 403)
    with closing(connect(db_path, create=False)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM item_settings").fetchone()[0] == 0


def test_absent_is_not_the_default(env):
    client, _, _ = env
    doc = client.get(API).json()
    assert doc == {"status": "ok", "revision": 0, "items": {"widget": {}, "plugin": {}}}
    item = client.get(LOG).json()
    assert item["values"] == {} and item["enabled"] is None and item["revision"] == 0
    assert item["schema"]["fields"]["showSystem"]["default"] is True
    client.patch(LOG, json={"values": {"showSystem": True}})
    client.patch(LOG, json={"values": {"showSystem": None}})
    assert client.get(LOG).json()["values"] == {}


def test_a_write_persists_publishes_and_reads_back_hierarchically(env):
    client, db_path, frames = env
    res = client.patch(LOG, json={"values": {"showSystem": False}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "committed" and body["values"] == {"showSystem": False}
    assert body["revision"] == 1
    assert frames == [{"type": "item_settings.changed", "revision": 1}]
    doc = client.get(API).json()
    assert doc["revision"] == 1
    assert doc["items"]["widget"] == {"core.activity-log": {"values": {"showSystem": False}, "revision": 1}}
    with closing(connect(db_path, create=False)) as conn:
        row = conn.execute("SELECT values_json, schema_version FROM item_settings").fetchone()
    assert row[0] == '{"showSystem": false}' and row[1] == 1


def test_an_identical_write_moves_no_revision_and_publishes_nothing(env):
    client, _, frames = env
    client.patch(LOG, json={"values": {"showSystem": False}})
    again = client.patch(LOG, json={"values": {"showSystem": False}})
    assert again.json()["status"] == "unchanged" and again.json()["revision"] == 1
    assert len(frames) == 1


@pytest.mark.parametrize("values, code, key", [
    ({"nope": 1}, "setting_unknown", "nope"),
    ({"nope": None}, "setting_unknown", "nope"),
    ({"wrap": 1}, "setting_type", "wrap"),
    ({"rows": True}, "setting_type", "rows"),
    ({"rows": "3"}, "setting_type", "rows"),
    ({"rows": 0}, "setting_below_min", "rows"),
    ({"rows": 51}, "setting_above_max", "rows"),
    ({"order": "sideways"}, "setting_not_an_option", "order"),
    ({"title": "toolong"}, "setting_too_long", "title"),
])
def test_each_refusal_is_named_and_writes_nothing(env, rich_widget, values, code, key):
    client, _, frames = env
    res = client.patch(rich_widget, json={"values": {"wrap": True, **values}})
    assert res.status_code == 400, res.text
    assert res.json()["detail"]["code"] == code and res.json()["detail"]["key"] == key
    assert client.get(rich_widget).json()["values"] == {} and frames == []


def test_the_bounds_themselves_are_accepted(env, rich_widget):
    client, _, _ = env
    assert client.patch(rich_widget, json={"values": {"rows": 1}}).status_code == 200
    assert client.patch(rich_widget, json={"values": {"rows": 50, "title": "12345"}}).status_code == 200


def test_unknown_items_kinds_and_bad_envelopes_are_refused(env):
    client, _, _ = env
    for path in (f"{API}/widget/core.nope", f"{API}/theme/core.notes"):
        assert client.get(path).json()["detail"]["code"] == "item_unknown"
        assert client.patch(path, json={"enabled": False}).status_code == 404
    res = client.patch(f"{API}/widget/core.terminal", json={"enabled": False})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "enabled_not_supported"
    assert client.patch(LOG, json={}).json()["detail"]["code"] == "empty_patch"
    assert client.patch(LOG, json={"values": {}, "colour": "x"}).status_code == 422
    assert client.patch(LOG, json={"enabled": "no"}).status_code == 422
    assert client.get(API).json()["revision"] == 0


def test_a_stale_revision_is_refused_with_the_current_item_and_a_retry_lands(env):
    client, _, _ = env
    first = client.patch(LOG, json={"values": {"showSystem": False}, "expected_revision": 0})
    assert first.status_code == 200
    stale = client.patch(LOG, json={"values": {"showSystem": True}, "expected_revision": 0})
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "item_settings_stale"
    assert detail["current"]["values"] == {"showSystem": False} and detail["current"]["revision"] == 1
    retry = client.patch(LOG, json={"values": {"showSystem": True},
                                    "expected_revision": detail["current"]["revision"]})
    assert retry.status_code == 200 and retry.json()["values"] == {"showSystem": True}


def test_revisions_are_document_monotonic_across_items(env):
    client, _, frames = env
    client.patch(LOG, json={"values": {"showSystem": False}})
    res = client.patch(f"{API}/widget/core.notes", json={"enabled": False})
    assert res.json()["revision"] == 2 and client.get(API).json()["revision"] == 2
    assert [f["revision"] for f in frames] == [1, 2]
    ok = client.patch(LOG, json={"values": {"showSystem": True}, "expected_revision": 1})
    assert ok.status_code == 200


def test_the_widget_switch_is_stored_and_listed(env):
    client, _, _ = env
    rows = {row["id"]: row for row in client.get("/api/v1/widgets").json()["widgets"]}
    assert rows["core.notes"]["enabled"] is True
    assert rows["core.terminal"]["enabled"] is None and rows["core.browser"]["enabled"] is None
    assert rows["core.activity-log"]["has_settings"] is True and rows["core.notes"]["has_settings"] is False
    client.patch(f"{API}/widget/core.notes", json={"enabled": False})
    rows = {row["id"]: row for row in client.get("/api/v1/widgets").json()["widgets"]}
    assert rows["core.notes"]["enabled"] is False
    assert client.get(API).json()["items"]["widget"]["core.notes"] == {"enabled": False, "revision": 1}


def test_a_stored_value_the_schema_now_refuses_is_dropped_not_repaired(env, rich_widget):
    client, db_path, _ = env
    client.patch(rich_widget, json={"values": {"rows": 40, "wrap": True}})
    with closing(connect(db_path, create=False)) as conn:
        conn.execute("UPDATE item_settings SET values_json = ? WHERE item_id = 'test.rich'",
                     ('{"rows": 99, "wrap": true, "gone": 1}',))
    item = client.get(rich_widget).json()
    assert item["values"] == {"wrap": True} and item["dropped"] == ["gone", "rows"]
    assert client.get(API).json()["items"]["widget"]["test.rich"]["values"] == {"wrap": True}


def test_a_registered_migration_runs_before_the_check(env, rich_widget, monkeypatch):
    client, db_path, _ = env
    with closing(connect(db_path, create=False)) as conn:
        conn.execute(
            "INSERT INTO item_settings (kind, item_id, enabled, schema_version, values_json, "
            "revision, updated_at) VALUES ('widget', 'test.rich', NULL, 0, '{\"lines\": 7}', 1, 'x')")
    monkeypatch.setitem(item_settings_schema.MIGRATIONS, ("widget", "test.rich", 0),
                        lambda values: {"rows": values.pop("lines")})
    assert client.get(rich_widget).json()["values"] == {"rows": 7}


def test_no_datastore_is_an_explicit_unavailable(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path / "none", raising=True)
    client = TestClient(_app(True))
    res = client.get(API)
    assert res.status_code == 503 and res.json()["detail"]["code"] == "item_settings_unavailable"


from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_gi_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_gi_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import session_groups_routes
from src.api.auth import require_auth
from src.api.session_group_icon_routes import router as icon_router
from src.api.session_groups_routes import router as groups_router
from src.core import db_models, icon_registry
from src.core import session_group_store as store
from src.core import session_group_style as style
from src.core.db import column_exists, connect, db_path_for, get_schema_version, set_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_steps import STEPS
from src.core.session_group_icon_ddl import ICON_COLUMN, REVERSAL_SQL_V39
from src.core.session_group_style_ddl import DDL_V33

TABLE = "session_group_styles"


def _drop_to_v38(state_dir: Path) -> None:
    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        with conn:
            conn.execute(f"ALTER TABLE {TABLE} DROP COLUMN {ICON_COLUMN}")
            set_meta(conn, db_models.META_SCHEMA_VERSION, "38")


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    from src.config import settings

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state_dir, raising=True)
    published = []
    monkeypatch.setattr(
        session_groups_routes.session_change_notice, "publish",
        lambda state, notice: published.append(notice),
    )
    assert ensure_db_migrated(state_dir).status == "ok"
    app = FastAPI()
    app.include_router(groups_router, prefix="/api/v1")
    app.include_router(icon_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        yield client, state_dir, published


def _new_group(client, name="work") -> str:
    body = client.post("/api/v1/session-groups", json={"name": name}).json()
    return next(g["group_uuid"] for g in body["groups"] if g["name"] == name)


def _group(client, uuid) -> dict:
    return next(
        g for g in client.get("/api/v1/session-groups").json()["groups"]
        if g["group_uuid"] == uuid
    )




def test_a_fresh_install_passes_v39_and_has_the_column(tmp_path):
    assert db_models.CURRENT_SCHEMA_VERSION >= 39
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION
        assert column_exists(conn, TABLE, ICON_COLUMN)


def test_a_v38_datastore_migrates_up_behind_a_verified_backup_and_keeps_its_styles(tmp_path):
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        made = store.create_group(conn, "infra")
        store.set_group_style(conn, made.group_uuid, "rose", "dusk", "pulse")
    _drop_to_v38(tmp_path)
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION
        assert column_exists(conn, TABLE, ICON_COLUMN)
        listed = store.list_groups(conn)[0]
        assert (listed.style.colour, listed.style.gradient, listed.style.animation) == (
            "rose", "dusk", "pulse")
        assert listed.style.icon is None
        trail = conn.execute(
            "SELECT status, backup_path, backup_verified FROM migration_trail "
            "WHERE from_version = '38' AND to_version = ?",
            (str(db_models.CURRENT_SCHEMA_VERSION),),
        ).fetchall()
    assert trail, "the migration from 38 left no trail entry"
    status, backup_path, verified = trail[-1]
    assert status.startswith("completed")
    assert verified == 1 and "bak-v38" in backup_path
    assert list(tmp_path.rglob(backup_path)), "the recorded backup is not on disk"


def test_the_step_is_idempotent_and_survives_a_missing_table():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE session_groups (id INTEGER PRIMARY KEY)")
    STEPS[38](conn)
    assert column_exists(conn, TABLE, ICON_COLUMN)
    conn.execute("DROP TABLE session_group_styles")
    for statement in DDL_V33:
        conn.execute(statement)
    conn.execute("INSERT INTO session_groups (id) VALUES (1)")
    conn.execute(
        "INSERT INTO session_group_styles (group_id, colour, animation, updated_at) "
        "VALUES (1, 'teal', 'none', 'x')"
    )
    STEPS[38](conn)
    STEPS[38](conn)
    assert conn.execute("SELECT colour, icon FROM session_group_styles").fetchall() == [("teal", None)]


def test_the_reversal_is_a_restore_that_names_what_it_loses():
    assert REVERSAL_SQL_V39 == ()
    assert db_models.REVERSAL_SQL_V39 == ()
    assert db_models.REVERSAL_DESTROYS[39] == ("session_group_styles.icon",)


def test_a_datastore_before_v39_still_lists_its_groups(tmp_path):
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        made = store.create_group(conn, "infra")
        store.set_group_style(conn, made.group_uuid, "gold")
        with conn:
            conn.execute(f"ALTER TABLE {TABLE} DROP COLUMN {ICON_COLUMN}")
        listed = store.list_groups(conn)[0]
        assert listed.style.colour == "gold" and listed.style.icon is None
        with pytest.raises(store.GroupsUnavailable):
            store.set_group_icon(conn, made.group_uuid, "flask")




def test_the_server_reads_the_pickers_own_registry():
    ids = icon_registry.known_ids()
    assert len(ids.current) >= 20
    assert {"folder", "flask", "terminal", "coffee"} <= ids.current
    assert "trash" not in ids.current


def test_a_registry_that_names_nothing_is_unavailable_not_empty(tmp_path):
    with pytest.raises(icon_registry.IconRegistryUnavailable):
        icon_registry.known_ids(tmp_path / "absent.js")
    blank = tmp_path / "blank.js"
    blank.write_text("export const ICON_REGISTRY = Object.freeze([]);\n", encoding="utf-8")
    with pytest.raises(icon_registry.IconRegistryUnavailable):
        icon_registry.known_ids(blank)


def test_a_retired_id_is_accepted_and_a_new_file_is_reread(tmp_path):
    reg = tmp_path / "icon-registry.js"
    reg.write_text(
        "export const ICON_REGISTRY = Object.freeze([\n"
        "    { id: 'folder', glyph: 'folder' },\n]);\n"
        "export const RETIRED_ICON_IDS = Object.freeze({ 'dir': 'folder' });\n",
        encoding="utf-8",
    )
    ids = icon_registry.known_ids(reg)
    assert ids.accepts("folder") and ids.accepts("dir") and not ids.accepts("flask")
    reg.write_text(
        "export const ICON_REGISTRY = Object.freeze([{ id: 'flask' }, { id: 'folder' }]);\n",
        encoding="utf-8",
    )
    assert icon_registry.known_ids(reg).accepts("flask")




def test_the_icon_and_the_colour_never_overwrite_each_other(tmp_path):
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        made = store.create_group(conn, "infra")
        store.set_group_style(conn, made.group_uuid, "teal", "tide", "shimmer")
        store.set_group_icon(conn, made.group_uuid, "flask")
        got = store.list_groups(conn)[0].style
        assert (got.colour, got.gradient, got.animation, got.icon) == (
            "teal", "tide", "shimmer", "flask")
        store.set_group_style(conn, made.group_uuid, "gold")
        assert store.list_groups(conn)[0].style.icon == "flask"
        store.set_group_icon(conn, made.group_uuid, None)
        got = store.list_groups(conn)[0].style
        assert (got.colour, got.icon) == ("gold", None)


def test_an_unstyled_group_keeps_its_derived_colour_when_given_an_icon(tmp_path):
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        made = store.create_group(conn, "legacy")
        with conn:
            conn.execute("DELETE FROM session_group_styles")
        store.set_group_icon(conn, made.group_uuid, "bolt")
        got = store.list_groups(conn)[0].style
        assert got.colour == style.derived_colour(made.group_uuid)
        assert got.icon == "bolt"




def test_put_icon_persists_announces_and_clears(app_env):
    client, _, published = app_env
    uuid = _new_group(client)
    assert _group(client, uuid)["icon"] is None
    published.clear()
    resp = client.put(f"/api/v1/session-groups/{uuid}/icon", json={"icon": "flask"})
    assert resp.status_code == 200
    assert next(g for g in resp.json()["groups"] if g["group_uuid"] == uuid)["icon"] == "flask"
    assert _group(client, uuid)["icon"] == "flask"
    assert len(published) == 1 and "groups" in str(published[0])
    assert client.put(f"/api/v1/session-groups/{uuid}/icon", json={"icon": None}).status_code == 200
    assert _group(client, uuid)["icon"] is None


def test_a_colour_pick_after_an_icon_keeps_the_icon(app_env):
    client, _, _ = app_env
    uuid = _new_group(client)
    client.put(f"/api/v1/session-groups/{uuid}/icon", json={"icon": "coffee"})
    client.put(f"/api/v1/session-groups/{uuid}/style", json={"colour": "violet"})
    got = _group(client, uuid)
    assert (got["colour"], got["icon"]) == ("violet", "coffee")


@pytest.mark.parametrize("bad", ["trash", "Flask", "", "../x", "flask "])
def test_an_unknown_icon_is_a_400_with_a_named_reason(app_env, bad):
    client, _, _ = app_env
    uuid = _new_group(client)
    resp = client.put(f"/api/v1/session-groups/{uuid}/icon", json={"icon": bad})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unknown_icon"
    assert _group(client, uuid)["icon"] is None


def test_the_icon_field_is_required_and_a_missing_group_is_a_404(app_env):
    client, _, _ = app_env
    uuid = _new_group(client)
    assert client.put(f"/api/v1/session-groups/{uuid}/icon", json={}).status_code == 422
    missing = client.put("/api/v1/session-groups/not-a-group/icon", json={"icon": "flask"})
    assert missing.status_code == 404


def test_an_unreadable_registry_is_a_503_not_an_accept(app_env, monkeypatch):
    client, _, _ = app_env
    uuid = _new_group(client)

    def _unavailable(path=None):
        raise icon_registry.IconRegistryUnavailable("the icon registry could not be read")

    monkeypatch.setattr(icon_registry, "known_ids", _unavailable)
    resp = client.put(f"/api/v1/session-groups/{uuid}/icon", json={"icon": "flask"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == icon_registry.UNAVAILABLE_CODE


def test_a_stored_id_this_build_does_not_know_is_passed_through(app_env):
    client, state_dir, _ = app_env
    uuid = _new_group(client)
    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        with conn:
            conn.execute("UPDATE session_group_styles SET icon = 'from-the-future'")
    assert _group(client, uuid)["icon"] == "from-the-future"


def test_the_icon_route_requires_auth(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    app = FastAPI()
    app.include_router(icon_router, prefix="/api/v1")
    with TestClient(app) as client:
        resp = client.put("/api/v1/session-groups/x/icon", json={"icon": "flask"})
    assert resp.status_code in (401, 403)

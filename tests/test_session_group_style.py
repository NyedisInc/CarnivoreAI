
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_gs_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_gs_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.session_groups_routes import router as groups_router
from src.core import db_models
from src.core import session_group_store as store
from src.core import session_group_style as style
from src.core.archive_db_partition import SIDE_APP, side_for_table
from src.core.db import connect, db_path_for, get_schema_version, table_exists
from src.core.db_migration import ensure_db_migrated
from src.core.db_schema_audit import UNGATED_VERSION_DDL
from src.core.db_steps import STEPS
from src.core.session_group_style_ddl import DDL_V33, REVERSAL_SQL_V33

REPO = Path(__file__).resolve().parents[1]
CSS = REPO / "client" / "css" / "session-sidebar-colours.css"


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    from src.config import settings

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state_dir, raising=True)
    assert ensure_db_migrated(state_dir).status == "ok"
    app = FastAPI()
    app.include_router(groups_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        yield client, state_dir




def test_a_fresh_install_reaches_v33_with_the_table(tmp_path):
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION >= 33
        assert table_exists(conn, "session_group_styles")


def test_the_step_is_idempotent_audited_partitioned_and_reversible():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE session_groups (id INTEGER PRIMARY KEY)")
    STEPS[32](conn)
    STEPS[32](conn)
    assert table_exists(conn, "session_group_styles")
    assert UNGATED_VERSION_DDL[33] == DDL_V33
    assert side_for_table("session_group_styles") == SIDE_APP
    assert db_models.REVERSAL_SQL_V33 == REVERSAL_SQL_V33
    assert db_models.REVERSAL_DESTROYS[33] == ("session_group_styles (whole table)",)
    for statement in REVERSAL_SQL_V33:
        conn.execute(statement)
    assert not table_exists(conn, "session_group_styles")




def test_derived_colour_is_stable_and_an_auto_colour():
    uuid = "816d608d-9b02-49eb-817a-9cf12a838fc9"
    first = style.derived_colour(uuid)
    assert first == style.derived_colour(uuid)
    assert first in style.AUTO_COLOURS
    assert not {"cyan", "violet", "yellow"} & set(style.AUTO_COLOURS)


def test_a_new_group_stores_a_random_auto_colour(tmp_path):
    ensure_db_migrated(tmp_path)
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        made = store.create_group(conn, "infra")
        assert made.style.colour in style.AUTO_COLOURS
        listed = store.list_groups(conn)[0]
        assert listed.style.source == style.SOURCE_STORED
        assert listed.style.colour == made.style.colour


def test_a_group_with_no_row_reads_its_derived_colour_and_delete_cascades(tmp_path):
    ensure_db_migrated(tmp_path)
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        made = store.create_group(conn, "legacy")
        with conn:
            conn.execute("DELETE FROM session_group_styles")
        listed = store.list_groups(conn)[0]
        assert listed.style.source == style.SOURCE_DERIVED
        assert listed.style.colour == style.derived_colour(made.group_uuid)
        store.set_group_style(conn, made.group_uuid, "rose", "dusk", "pulse")
        store.delete_group(conn, made.group_uuid)
        assert conn.execute("SELECT COUNT(*) FROM session_group_styles").fetchone()[0] == 0




def test_every_group_on_the_wire_carries_its_style(app_env):
    client, _ = app_env
    body = client.post("/api/v1/session-groups", json={"name": "work"}).json()
    group = body["groups"][0]
    assert group["colour"] in style.AUTO_COLOURS
    assert group["gradient"] is None
    assert group["animation"] == "none"
    assert group["style_source"] == "stored"


def test_put_style_persists_across_a_fresh_read(app_env):
    client, _ = app_env
    uuid = client.post("/api/v1/session-groups", json={"name": "work"}).json()["groups"][0]["group_uuid"]
    resp = client.put(
        f"/api/v1/session-groups/{uuid}/style",
        json={"colour": "teal", "gradient": "tide", "animation": "shimmer"},
    )
    assert resp.status_code == 200
    group = client.get("/api/v1/session-groups").json()["groups"][0]
    assert (group["colour"], group["gradient"], group["animation"]) == ("teal", "tide", "shimmer")
    client.put(f"/api/v1/session-groups/{uuid}/style", json={"colour": "gold"})
    group = client.get("/api/v1/session-groups").json()["groups"][0]
    assert (group["colour"], group["gradient"], group["animation"]) == ("gold", None, "none")


@pytest.mark.parametrize(
    "payload",
    [
        {"colour": "#ff00"},
        {"colour": "red"},
        {"colour": "teal", "gradient": "rainbow"},
        {"colour": "teal", "animation": "strobe"},
    ],
)
def test_a_key_outside_the_palette_is_a_400(app_env, payload):
    client, _ = app_env
    uuid = client.post("/api/v1/session-groups", json={"name": "work"}).json()["groups"][0]["group_uuid"]
    assert client.put(f"/api/v1/session-groups/{uuid}/style", json=payload).status_code == 400


def test_a_custom_hex_is_stored_lowercase_and_listed(app_env):
    client, _ = app_env
    uuid = client.post("/api/v1/session-groups", json={"name": "work"}).json()["groups"][0]["group_uuid"]
    resp = client.put(f"/api/v1/session-groups/{uuid}/style", json={"colour": "#6C799F", "animation": "pulse"})
    assert resp.status_code == 200
    group = resp.json()["groups"][0]
    assert (group["colour"], group["gradient"], group["animation"], group["style_source"]) == ("#6c799f", None, "pulse", "stored")
    assert client.get("/api/v1/session-groups").json()["groups"][0]["colour"] == "#6c799f"


def test_an_unknown_group_is_a_404(app_env):
    client, _ = app_env
    resp = client.put("/api/v1/session-groups/nope/style", json={"colour": "teal"})
    assert resp.status_code == 404




def test_the_stylesheet_carries_a_rule_for_every_key_and_no_colour_literal():
    css = CSS.read_text()
    for key in style.COLOURS:
        assert f'[data-group-colour="{key}"]' in css, key
    for key in style.GRADIENTS:
        assert f'[data-group-gradient="{key}"]' in css, key
    for key in style.ANIMATIONS[1:]:
        assert f'[data-group-anim="{key}"]' in css, key
    assert "prefers-reduced-motion" in css
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", rules)


def test_the_client_picker_mirrors_the_server_keys():
    js = (REPO / "client" / "js" / "session-sidebar-group-colour.js").read_text()

    def listed(name):
        match = re.search(rf"const {name} = \[([^\]]*)\]", js)
        assert match, name
        return tuple(re.findall(r"'([a-z]+)'", match.group(1)))

    assert listed("COLOURS") == style.COLOURS
    assert listed("GRADIENTS") == style.GRADIENTS
    assert listed("ANIMATIONS") == style.ANIMATIONS

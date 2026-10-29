
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tests.layouts_helpers import add_sessions, client_for, grid, row

# ruff: noqa: E402
from src.core import db_models
from src.core.layouts import style as style
from src.core.layouts import store as store
from src.core.archive_db_partition import SIDE_APP, side_for_table
from src.core.db import connect, db_path_for, get_schema_version, table_exists
from src.core.db_migration import ensure_db_migrated
from src.core.db_schema_audit import UNGATED_VERSION_DDL
from src.core.db_steps import STEPS
from src.core.layouts.style_ddl import DDL_V36, REVERSAL_SQL_V36
from src.core.session_group_style import COLOURS as GROUP_COLOURS

REPO = Path(__file__).resolve().parents[1]
CSS = REPO / "client" / "css" / "session-sidebar-colours.css"
API = "/api/v1/layouts"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    client, db_path, frames = client_for(tmp_path, monkeypatch)
    return client, db_path, frames, add_sessions(db_path, 4)


def _create(client, name, *rows_, **extra):
    return client.post(API, json={"name": name, "shape": grid(*[row(r) for r in rows_]), **extra})




def test_a_fresh_install_reaches_v36_with_the_table(tmp_path):
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION >= 36
        assert table_exists(conn, "layout_styles")


def test_the_step_is_idempotent_audited_partitioned_and_reversible():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE layouts (id INTEGER PRIMARY KEY, layout_uuid TEXT UNIQUE)")
    STEPS[35](conn)
    STEPS[35](conn)
    assert table_exists(conn, "layout_styles")
    assert UNGATED_VERSION_DDL[36] == DDL_V36
    assert side_for_table("layout_styles") == SIDE_APP
    assert db_models.REVERSAL_SQL_V36 == REVERSAL_SQL_V36
    assert db_models.REVERSAL_DESTROYS[36] == ("layout_styles (whole table)",)
    for statement in REVERSAL_SQL_V36:
        conn.execute(statement)
    assert not table_exists(conn, "layout_styles")




def test_the_palette_is_the_group_palette_not_a_second_copy():
    assert style.COLOURS == GROUP_COLOURS
    assert style.DEFAULT_COLOUR not in style.COLOURS
    assert not ({"cyan", "violet", "yellow"} & set(style.AUTO_COLOURS))


def test_the_default_colour_is_named_in_the_stylesheet():
    css = CSS.read_text(encoding="utf-8")
    assert "--drawer-hue-indigo" in css




def test_a_new_layout_stores_a_random_auto_colour(tmp_path):
    ensure_db_migrated(tmp_path)
    db_path = db_path_for(tmp_path)
    sessions = add_sessions(db_path, 2)
    with closing(connect(db_path, create=False)) as conn:
        (a, _), (b, _) = sessions
        made = store.create_layout(conn, "pair", grid(row(a), row(b)))
        assert made.layout.colour in style.AUTO_COLOURS
        assert made.layout.style_source == style.SOURCE_STORED
        listed = store.list_layouts(conn)[0]
        assert listed.colour == made.layout.colour


def test_a_layout_with_no_row_reads_the_fixed_default_and_delete_cascades(tmp_path):
    ensure_db_migrated(tmp_path)
    db_path = db_path_for(tmp_path)
    sessions = add_sessions(db_path, 2)
    with closing(connect(db_path, create=False)) as conn:
        (a, _), (b, _) = sessions
        made = store.create_layout(conn, "pair", grid(row(a), row(b)))
        uuid = made.layout.layout_uuid
        conn.execute("DELETE FROM layout_styles WHERE layout_uuid = ?", (uuid,))
        conn.commit()
        unstyled = store.get_layout(conn, uuid)
        assert unstyled.colour == style.DEFAULT_COLOUR
        assert unstyled.style_source == style.SOURCE_DERIVED
        store.set_layout_style(conn, uuid, "teal", "tide", "shimmer")
        assert conn.execute(
            "SELECT COUNT(*) FROM layout_styles WHERE layout_uuid = ?", (uuid,)
        ).fetchone()[0] == 1
        store.delete_layout(conn, uuid)
        assert conn.execute(
            "SELECT COUNT(*) FROM layout_styles WHERE layout_uuid = ?", (uuid,)
        ).fetchone()[0] == 0


def test_set_layout_style_validates_and_replaces_the_whole_style(tmp_path):
    ensure_db_migrated(tmp_path)
    db_path = db_path_for(tmp_path)
    sessions = add_sessions(db_path, 2)
    with closing(connect(db_path, create=False)) as conn:
        (a, _), (b, _) = sessions
        made = store.create_layout(conn, "pair", grid(row(a), row(b)))
        uuid = made.layout.layout_uuid
        store.set_layout_style(conn, uuid, "teal", "tide", "shimmer")
        again = store.set_layout_style(conn, uuid, "gold")
        assert again.layout.colour == "gold"
        assert again.layout.gradient is None
        assert again.layout.animation == "none"
        with pytest.raises(style.LayoutStyleInvalid):
            store.set_layout_style(conn, uuid, "not-a-colour")


def test_set_layout_style_404s_on_no_such_layout(tmp_path):
    ensure_db_migrated(tmp_path)
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        with pytest.raises(store.LayoutNotFound):
            store.set_layout_style(conn, "no-such-uuid", "teal")




def test_route_sets_style_and_publishes(env):
    client, _, frames, sessions = env
    (a, _), (b, _) = sessions[:2]
    created = _create(client, "pair", a, b).json()["layout"]
    uuid = created["layout_uuid"]
    assert created["colour"] == created["colour"]
    res = client.put(f"{API}/{uuid}/style",
                     json={"colour": "teal", "gradient": "tide", "animation": "shimmer"})
    assert res.status_code == 200, res.text
    layout = res.json()["layout"]
    assert layout["colour"] == "teal"
    assert layout["gradient"] == "tide"
    assert layout["animation"] == "shimmer"
    assert frames[-1]["reason"] == "layouts"
    listed = client.get(API).json()["layouts"][0]
    assert listed["colour"] == "teal" and listed["gradient"] == "tide"


def test_route_refuses_an_invalid_style(env):
    client, _, _, sessions = env
    (a, _), (b, _) = sessions[:2]
    uuid = _create(client, "pair", a, b).json()["layout"]["layout_uuid"]
    for body in (
        {"colour": "not-a-colour"},
        {"colour": "teal", "gradient": "not-a-gradient"},
        {"colour": "teal", "animation": "not-an-animation"},
    ):
        res = client.put(f"{API}/{uuid}/style", json=body)
        assert res.status_code == 400, body
        assert res.json()["detail"]["code"] == "layout_style_invalid"


def test_route_404s_on_no_such_layout(env):
    client, _, _, _ = env
    res = client.put(f"{API}/no-such-uuid/style", json={"colour": "teal"})
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "layout_not_found"


def test_route_accepts_a_custom_hex_and_stores_it_lowercase(env):
    client, _, _, sessions = env
    (a, _), (b, _) = sessions[:2]
    uuid = _create(client, "pair", a, b).json()["layout"]["layout_uuid"]
    res = client.put(f"{API}/{uuid}/style", json={"colour": "#956B8B", "animation": "pulse"})
    assert res.status_code == 200, res.text
    layout = res.json()["layout"]
    assert (layout["colour"], layout["gradient"], layout["animation"]) == ("#956b8b", None, "pulse")
    assert client.put(f"{API}/{uuid}/style", json={"colour": "#12345"}).status_code == 400


def test_route_rejects_unknown_fields(env):
    client, _, _, sessions = env
    (a, _), (b, _) = sessions[:2]
    uuid = _create(client, "pair", a, b).json()["layout"]["layout_uuid"]
    res = client.put(f"{API}/{uuid}/style", json={"colour": "teal", "bogus": 1})
    assert res.status_code == 422

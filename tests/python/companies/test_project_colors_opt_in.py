
from __future__ import annotations

from contextlib import closing

from src.core.db import connect, db_path_for
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain

API = "/api/v1"
TRIGGER = "trg_projects_color"
INSERT = (
    "INSERT INTO projects (root, raw_path, display_name, source, color, created_at, updated_at) "
    "VALUES (?, ?, ?, 'user', ?, 'x', 'x')"
)


def _triggers(conn) -> set:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}


def _colors(conn) -> list:
    return [row[0] for row in conn.execute("SELECT color FROM projects ORDER BY id")]


def test_projects_have_no_color_until_picked_and_can_be_cleared(tmp_path, client):
    with closing(connect(db_path_for(tmp_path))) as conn:
        with conn:
            run_chain(conn, 0, 90)
            for i, color in enumerate(("orange", "cyan", "green-bright", "#966356")):
                conn.execute(INSERT, (f"/o{i}", f"/o{i}", f"o{i}", color))
        assert [c for c in _colors(conn) if c] == ["orange", "cyan", "green-bright", "#966356"]
        assert TRIGGER in _triggers(conn)
        with conn:
            run_chain(conn, 90, CURRENT_SCHEMA_VERSION)
        assert _colors(conn) == [None, None, None, "#966356"]
        assert TRIGGER not in _triggers(conn)
        with conn:
            run_chain(conn, 90, CURRENT_SCHEMA_VERSION)
        assert _colors(conn) == [None, None, None, "#966356"]
        with conn:
            conn.execute(INSERT, ("/n", "/n", "n", None))
        assert _colors(conn)[-1] is None

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    with closing(connect(db_path_for(fresh))) as conn:
        with conn:
            run_chain(conn, 0, CURRENT_SCHEMA_VERSION)
            conn.execute(INSERT, ("/f", "/f", "f", None))
        assert TRIGGER not in _triggers(conn) and _colors(conn) == [None]

    created = client.post(f"{API}/projects", json={"name": "gamma", "path": str(tmp_path / "gamma")})
    assert created.status_code in (200, 201), created.text
    read = lambda: next(p for p in client.get(f"{API}/projects").json() if p["name"] == "gamma")["color"]
    assert read() is None
    assert client.patch(f"{API}/projects/gamma", json={"color": "#966356"}).json()["color"] == "#966356"
    assert read() == "#966356"
    cleared = client.patch(f"{API}/projects/gamma", json={"color": ""})
    assert cleared.status_code == 200 and cleared.json()["color"] is None
    assert read() is None
    assert client.patch(f"{API}/projects/gamma", json={"color": "nope"}).status_code == 422


from __future__ import annotations

from contextlib import closing
from pathlib import Path

from src.core.db import connect, db_path_for
from src.core.db_steps import run_chain
from src.core.project_colors.legacy_keys import LEGACY_KEYS, cycle_key

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[3]


def _project(client, name):
    return next(p for p in client.get(f"{API}/projects").json() if p["name"] == name)


def test_v60_database_is_backfilled_round_robin_and_idempotent(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, 60)
        for i in range(len(LEGACY_KEYS) + 2):
            conn.execute(
                "INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) "
                f"VALUES ('/r{i}', '/r{i}', 'p{i}', 'user', 'x', 'x')"
            )
        assert "color" not in {r[1] for r in conn.execute("PRAGMA table_info(projects)")}
        with conn:
            run_chain(conn, 60, 61)
        colors = [r[0] for r in conn.execute("SELECT color FROM projects ORDER BY id")]
        assert colors == [cycle_key(i) for i in range(len(LEGACY_KEYS) + 2)]
        assert colors[0] != colors[1]
        from src.core.project_colors.ddl import apply_v61

        with conn:
            apply_v61(conn)
        assert [r[0] for r in conn.execute("SELECT color FROM projects ORDER BY id")] == colors


def test_projects_read_carries_color(client):
    assert _project(client, "alpha")["color"] is None


def test_patch_color_sets_it_and_takes_a_hex_and_refuses_a_malformed_one(client):
    r = client.patch(f"{API}/projects/alpha", json={"color": "#b098f3"})
    assert r.status_code == 200 and r.json()["color"] == "#b098f3"
    assert _project(client, "alpha")["color"] == "#b098f3"
    assert client.patch(f"{API}/projects/alpha", json={"color": "#12"}).status_code == 422
    assert client.patch(f"{API}/projects/alpha", json={"color": "pink"}).status_code == 422
    assert client.patch(f"{API}/projects/alpha", json={"color": "violet"}).status_code == 422
    assert client.patch(f"{API}/projects/nope", json={"color": "#4fc1ff"}).status_code == 404
    assert _project(client, "alpha")["color"] == "#b098f3"
    assert client.patch(f"{API}/projects/alpha", json={"color": "#C17B87"}).json()["color"] == "#c17b87"


def test_projects_list_mcp_tool_carries_color(world):
    import asyncio

    from src.core.mcp import tools

    result = asyncio.run(tools.projects_list(None, None, {}))
    text = str(result)
    assert "'color'" in text or '"color"' in text


def test_the_web_palette_has_no_legacy_color_names():
    source = (ROOT / "web/src/lib/project-colors/palette.ts").read_text()
    assert "const PROJECT_COLORS" not in source and "isLegacyColorKey" not in source

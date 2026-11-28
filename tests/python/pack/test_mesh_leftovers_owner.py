
from __future__ import annotations

import os
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lo_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lo_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi.testclient import TestClient  # noqa: E402

from src.api import peer_auth  # noqa: E402
from src.api.auth import create_access_token  # noqa: E402
from src.core.api_keys import store as api_key_store  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.pack.machines import capabilities  # noqa: E402
from src.core.pack.meshdata import star_era  # noqa: E402
from src.core.pack.relay import member_reach  # noqa: E402
from src.core.pack.rollup_import.ddl import COUNTER_TABLE, PROJECTS_TABLE, REV_TABLE, STATE_TABLE, USAGE_TABLE  # noqa: E402
from src.main import app  # noqa: E402
from tests.python.pack.test_mesh_preflip import _fixture, _held  # noqa: E402

URL = "/api/v1/pack/leftovers"
TABLES = (USAGE_TABLE, COUNTER_TABLE, STATE_TABLE, PROJECTS_TABLE, REV_TABLE)


@pytest.fixture()
def world(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    conn = _fixture(tmp_path)
    for origin in ("iid-listed", "iid-star", "iid-ssh", "iid-recent", "iid-leftover"):
        conn.execute(f"INSERT INTO {PROJECTS_TABLE} (peer_install_id, project, name) VALUES (?, 'p', 'proj')", (origin,))
        conn.execute(f"INSERT INTO {REV_TABLE} (peer_install_id, conversation_id, hour, rev) VALUES (?, 'c', 1, 1)", (origin,))
    conn.execute(f"UPDATE {STATE_TABLE} SET label = 'old mac' WHERE peer_install_id = 'iid-leftover'")
    conn.commit()
    conn.close()
    path = db_path_for(tmp_path / "me")
    held = {"v": _held(["iid-listed", "iid-other"])}
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(path))
    monkeypatch.setattr(member_reach, "held_v2", lambda: held["v"])

    class W:
        client = TestClient(app)
        head = {"Authorization": "Bearer " + create_access_token()[0]}
        db = staticmethod(lambda: connect(path))
        held_box = held

    return W


def _rows(w, origin: str) -> dict:
    with closing(w.db()) as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE peer_install_id = ?", (origin,)).fetchone()[0] for t in TABLES}


def test_the_list_holds_exactly_the_leftover_with_what_the_owner_decides_on(world):
    r = world.client.get(URL, headers=world.head)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["known"] is True
    [row] = body["leftovers"]
    assert row["install_id"] == "iid-leftover" and row["name"] == "old mac" and row["newest_at"] > 0
    assert row["rows"] == {"usage": 1, "counters": 1, "projects": 1, "groups": 1}
    with closing(world.db()) as conn:
        assert star_era.find_leftovers(conn, world.held_box["v"]).counts["leftover"] == 1


def test_the_name_is_the_id_when_no_record_names_it(world):
    with closing(world.db()) as conn:
        conn.execute(f"UPDATE {STATE_TABLE} SET label = NULL WHERE peer_install_id = 'iid-leftover'")
        conn.commit()
    assert world.client.get(URL, headers=world.head).json()["leftovers"][0]["name"] == "iid-leftover"


def test_the_delete_removes_only_that_origins_rows_from_every_table(world):
    before = {o: _rows(world, o) for o in ("iid-listed", "iid-star", "iid-ssh", "iid-recent", "iid-leftover")}
    assert all(v > 0 for v in before["iid-leftover"].values())
    r = world.client.delete(f"{URL}/iid-leftover", headers=world.head)
    assert r.status_code == 200 and r.json() == {"forgotten": "iid-leftover"}
    assert _rows(world, "iid-leftover") == {t: 0 for t in TABLES}
    for origin in ("iid-listed", "iid-star", "iid-ssh", "iid-recent"):
        assert _rows(world, origin) == before[origin]
    assert world.client.get(URL, headers=world.head).json()["leftovers"] == []


@pytest.mark.parametrize("origin", ["iid-listed", "iid-star", "iid-ssh", "iid-recent", "iid-nobody"])
def test_the_delete_refuses_every_origin_that_is_not_a_leftover(world, origin):
    before = {t: _rows(world, origin) for t in (0,)}
    r = world.client.delete(f"{URL}/{origin}", headers=world.head)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "leftovers_not_leftover"
    assert {t: _rows(world, origin) for t in (0,)} == before


def test_a_leftover_that_still_supplies_another_origin_is_kept(world):
    with closing(world.db()) as conn:
        conn.execute(f"UPDATE {STATE_TABLE} SET via = 'iid-leftover' WHERE peer_install_id = 'iid-recent'")
        conn.commit()
    r = world.client.delete(f"{URL}/iid-leftover", headers=world.head)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "leftovers_supplies_others"
    assert _rows(world, "iid-leftover")[USAGE_TABLE] == 1 and _rows(world, "iid-recent")[USAGE_TABLE] == 1


def test_with_no_held_list_nothing_is_listed_and_nothing_is_deleted(world):
    world.held_box["v"] = None
    assert world.client.get(URL, headers=world.head).json() == {"known": False, "leftovers": []}
    r = world.client.delete(f"{URL}/iid-leftover", headers=world.head)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "leftovers_list_unknown"
    assert _rows(world, "iid-leftover")[USAGE_TABLE] == 1


def test_only_the_owners_own_sign_in_reaches_either_route(world, monkeypatch):
    from src.api import auth as auth_module, pack_removed_logins_routes as owner

    monkeypatch.setattr(api_key_store, "is_api_key", lambda v: str(v).startswith("cak_"))
    monkeypatch.setattr(owner, "is_api_key", lambda v: str(v).startswith("cak_"))

    async def admit(_token, _request):
        return {}

    monkeypatch.setattr(auth_module.api_key_gate, "admit", admit)
    key = {"Authorization": "Bearer cak_fixture"}
    for r in (world.client.get(URL, headers=key), world.client.delete(f"{URL}/iid-leftover", headers=key)):
        assert r.status_code == 403 and r.json()["detail"]["code"] == "leftovers_owner_only"
    assert _rows(world, "iid-leftover")[USAGE_TABLE] == 1
    assert world.client.get(URL, headers=world.head).status_code == 200


def test_with_the_switch_off_both_routes_are_the_unknown_path_404(world, monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert world.client.get(URL).status_code == 404 and world.client.delete(f"{URL}/iid-leftover").status_code == 404
    assert world.client.get(URL, headers=world.head).status_code == 404


def test_the_mcp_tool_is_a_read_with_a_short_description_and_there_is_no_delete_tool():
    from src.core.mcp import pack_leftovers_tools

    assert set(pack_leftovers_tools.READ_TOOLS) == {"pack_leftovers_list"} and not pack_leftovers_tools.WRITE_TOOLS
    [spec] = pack_leftovers_tools.SPECS
    assert len(spec.description) < 400
    from src.core.mcp import tools as mcp_tools

    names = {getattr(t, "name", None) for t in getattr(mcp_tools, "ALL_TOOLS", [])} if hasattr(mcp_tools, "ALL_TOOLS") else set()
    assert not any(n and "leftover" in n and ("delete" in n or "forget" in n) for n in names)


def test_the_mesh_doc_no_longer_calls_the_finder_read_only_with_no_caller():
    text = (Path(__file__).resolve().parents[3] / "docs" / "pack-mesh.md").read_text()
    assert "read-only finder with no caller" not in text
    assert "nothing in this change deletes any data" not in text

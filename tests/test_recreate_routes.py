
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.auth import require_auth  # noqa: E402
from src.api import recreate_routes  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.session_recreate_presence import (  # noqa: E402
    TMUX_GONE,
    TMUX_PRESENT,
    TMUX_UNKNOWN,
    TmuxPresence,
)

NAME = "cloude_recreate_demo"
ROW_UUID = "row-uuid-recreate"
CONV_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    from src.config import settings

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(
        type(settings), "get_state_dir", lambda self: state_dir, raising=True
    )
    monkeypatch.setattr(
        recreate_routes, "_socket_name", lambda: "cloude", raising=True
    )
    assert ensure_db_migrated(state_dir).status == "ok"

    app = FastAPI()
    app.include_router(recreate_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        yield client, state_dir, monkeypatch


def _presence(monkeypatch, outcome, detail="measured in the test"):
    monkeypatch.setattr(
        recreate_routes,
        "_measure_presence",
        lambda name, socket_name: TmuxPresence(outcome=outcome, detail=detail),
        raising=True,
    )


def _insert(state_dir, **overrides):
    row = {
        "session_uuid": ROW_UUID,
        "tmux_name": NAME,
        "tmux_created_epoch": 1788821572,
        "working_dir": "/Users/x/proj",
        "claude_session_uuid": CONV_UUID,
        "title": "fix the deploy script",
    }
    row.update(overrides)
    if row["session_uuid"] != ROW_UUID and "claude_session_uuid" not in overrides:
        row["claude_session_uuid"] = f"{row['session_uuid']}-conv"
    with connect(db_path_for(state_dir), create=False) as conn:
        conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, "
            "tmux_created_epoch, working_dir, claude_session_uuid, title, "
            "origin, lifecycle, created_at, updated_at) "
            "VALUES (?, 'cloude', ?, ?, ?, ?, ?, 'created', 'stopped', "
            "'2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')",
            (
                row["session_uuid"],
                row["tmux_name"],
                row["tmux_created_epoch"],
                row["working_dir"],
                row["claude_session_uuid"],
                row["title"],
            ),
        )
    return row["session_uuid"]


def test_a_gone_session_previews_a_recreate(app_env):
    client, state_dir, mp = app_env
    _insert(state_dir)
    _presence(mp, TMUX_GONE, "not on the socket")

    r = client.get(
        "/api/v1/sessions/recreate/preview", params={"session_uuid": ROW_UUID}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pane_state"] == "dead"
    assert body["unchanged"]["actionable"] is False, (
        "an unpicked recreate is never offered - there is no recorded "
        "start command left to fall back on"
    )
    assert body["name"] == "fix the deploy script"


def test_a_live_session_previews_alive_and_offers_nothing(app_env):
    client, state_dir, mp = app_env
    _insert(state_dir)
    _presence(mp, TMUX_PRESENT, "still on the socket")

    r = client.get(
        "/api/v1/sessions/recreate/preview", params={"session_uuid": ROW_UUID}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pane_state"] == "alive"
    assert body["unchanged"]["kind"] == "not_dead"
    assert all(o["actionable_now"] is False for o in body["options"])


def test_an_unmeasured_socket_previews_unknown_and_offers_nothing(app_env):
    client, state_dir, mp = app_env
    _insert(state_dir)
    _presence(mp, TMUX_UNKNOWN, "could not list the socket")

    r = client.get(
        "/api/v1/sessions/recreate/preview", params={"session_uuid": ROW_UUID}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pane_state"] == "unknown"
    assert body["unchanged"]["kind"] == "cannot_determine"
    assert all(o["actionable_now"] is False for o in body["options"])


def test_a_uuid_no_record_carries_is_a_404(app_env):
    client, _, mp = app_env
    _presence(mp, TMUX_GONE)
    r = client.get(
        "/api/v1/sessions/recreate/preview", params={"session_uuid": "no-such-row"}
    )
    assert r.status_code == 404


def test_a_row_that_never_had_a_tmux_session_is_a_409(app_env):
    client, state_dir, mp = app_env
    _insert(state_dir, tmux_name=None, tmux_created_epoch=None)
    _presence(mp, TMUX_GONE)

    r = client.get(
        "/api/v1/sessions/recreate/preview", params={"session_uuid": ROW_UUID}
    )
    assert r.status_code == 409
    assert "imported" in r.json()["detail"]


def test_the_route_is_addressed_by_the_durable_key_not_by_the_tmux_name():
    from src.api.recreate_routes import RecreateRequest

    fields = set(RecreateRequest.model_fields)
    assert "session_uuid" in fields
    assert "session_name" not in fields, (
        "the caller supplies the durable key; the tmux name is read off "
        "the row it resolves"
    )


def test_the_action_refuses_a_live_session_and_spawns_nothing(app_env):
    client, state_dir, mp = app_env
    _insert(state_dir)
    _presence(mp, TMUX_PRESENT, "still on the socket")

    r = client.post(
        "/api/v1/sessions/recreate",
        json={"session_uuid": ROW_UUID, "agent_type": "claude"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "refused"
    assert body["presence"] == "present"
    assert body["session_uuid"] == ROW_UUID
    assert body["detail"]


def test_the_action_refuses_an_unconfigured_wrapper(app_env):
    client, state_dir, mp = app_env
    _insert(state_dir)
    _presence(mp, TMUX_GONE)

    r = client.post(
        "/api/v1/sessions/recreate",
        json={"session_uuid": ROW_UUID, "agent_type": "not-a-configured-wrapper"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "refused"




def test_the_row_keeps_its_id_project_and_title_across_the_rekey(tmp_path):
    from src.core.session_restart import rebind_instance

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    assert ensure_db_migrated(state_dir).status == "ok"
    uuid = _insert(state_dir)

    db = db_path_for(state_dir)
    with connect(db, create=False) as conn:
        conn.execute(
            "INSERT INTO projects (root, raw_path, display_name, source, "
            "created_at, updated_at) VALUES ('/Users/x/proj', '/Users/x/proj', "
            "'proj', 'declared', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        project_id = conn.execute(
            "SELECT id FROM projects WHERE display_name = 'proj'"
        ).fetchone()[0]
        conn.execute(
            "UPDATE sessions SET project_id = ?, project_attribution = "
            "'declared' WHERE session_uuid = ?",
            (project_id, uuid),
        )
        before = dict(
            conn.execute(
                "SELECT * FROM sessions WHERE session_uuid = ?", (uuid,)
            ).fetchone()
        )

        result = rebind_instance(
            conn,
            row_id=int(before["id"]),
            socket="cloude",
            name=NAME,
            epoch=1788999999,
            tmux_session_id="$9",
            working_dir=before["working_dir"],
        )
        conn.commit()
        after = dict(
            conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (before["id"],)
            ).fetchone()
        )

    assert result.rebound is True, result.detail
    assert before["tmux_created_epoch"] != after["tmux_created_epoch"]
    assert after["tmux_created_epoch"] == 1788999999
    assert after["id"] == before["id"]
    assert after["session_uuid"] == uuid
    assert after["title"] == before["title"]
    assert after["project_id"] == project_id
    assert after["project_attribution"] == "declared"
    assert after["claude_session_uuid"] == CONV_UUID
    with connect(db, create=False) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE session_uuid = ?", (uuid,)
        ).fetchone()[0] == 1


def test_group_membership_is_keyed_on_the_session_and_survives_the_rekey(
    tmp_path,
):
    from src.core.session_restart import rebind_instance

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    assert ensure_db_migrated(state_dir).status == "ok"
    uuid = _insert(state_dir)

    with connect(db_path_for(state_dir), create=False) as conn:
        cols = {
            r["name"]
            for r in conn.execute(
                "PRAGMA table_info(session_group_membership)"
            ).fetchall()
        }
        assert "session_uuid" in cols and "tmux_name" not in cols

        conn.execute(
            "INSERT INTO session_groups (group_uuid, name, position, "
            "created_at, updated_at) VALUES ('grp-uuid-1', 'work', 0, "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        group_id = conn.execute(
            "SELECT id FROM session_groups WHERE name = 'work'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO session_group_membership (session_uuid, group_id, "
            "position, added_at) VALUES (?, ?, 3, '2026-01-01T00:00:00Z')",
            (uuid, group_id),
        )
        row_id = conn.execute(
            "SELECT id FROM sessions WHERE session_uuid = ?", (uuid,)
        ).fetchone()[0]

        assert rebind_instance(
            conn,
            row_id=int(row_id),
            socket="cloude",
            name=NAME,
            epoch=1788999999,
        ).rebound is True
        conn.commit()

        kept = conn.execute(
            "SELECT group_id, position FROM session_group_membership "
            "WHERE session_uuid = ?",
            (uuid,),
        ).fetchone()

    assert kept is not None, "the recreate orphaned the session's group filing"
    assert kept["group_id"] == group_id
    assert kept["position"] == 3


def test_the_preview_baseline_comes_from_the_recorded_launch(app_env):
    from types import SimpleNamespace

    client, state_dir, mp = app_env
    _insert(state_dir)
    with connect(db_path_for(state_dir), create=False) as conn:
        conn.execute(
            "UPDATE sessions SET agent_type='claude', agent_family='claude', "
            "agent_family_source='launched' WHERE session_uuid=?",
            (ROW_UUID,),
        )
    _presence(mp, TMUX_GONE, "not on the socket")

    def offer(agent_type):
        return SimpleNamespace(
            agent_type=agent_type, label=agent_type, family="claude",
            icon=None, command=f"{agent_type} --x",
        )

    class _Dir:
        refuses = False
        working_dir = "/w"
        detail = ""

    mp.setattr(
        recreate_routes, "resume_directory", lambda *a, **k: _Dir(), raising=True
    )
    mp.setattr(
        recreate_routes, "resolve_wrapper_offers",
        lambda *a, **k: [offer("claude"), offer("other")], raising=True,
    )
    mp.setattr(
        recreate_routes, "validate_agent_choice",
        lambda settings, agent_type, **k: SimpleNamespace(
            verdict="accepted", command=f"{agent_type} --x", detail="ok"),
        raising=True,
    )
    body = client.get(
        "/api/v1/sessions/recreate/preview", params={"session_uuid": ROW_UUID}
    ).json()
    assert body["unchanged"]["kind"] != "cannot_determine"
    assert body["unchanged"]["actionable"] is True
    folded = [o["agent_type"] for o in body["options"] if o["same_as_unchanged"]]
    assert folded == ["claude"]

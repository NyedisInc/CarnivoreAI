
from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp())
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp())
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for, set_meta, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    META_SESSION_IMPORT_UNATTRIBUTED,
    SESSION_ORIGIN_ADOPTED,
    SESSION_ORIGIN_CREATED,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.session_identity import record_instance
from src.core.session_import_promote import record_decline

SOCKET = "cloude"
STAMP = "2026-08-24T13:32:31Z"


class _Manager:

    def tmux_socket_name(self):
        return SOCKET


def _client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import routes
    from src.api import session_attribution_routes
    from src.api.auth import require_auth
    from src.api.routes import router

    monkeypatch.setattr(
        type(session_attribution_routes.settings), "get_state_dir", lambda self: tmp_path
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.session_manager = _Manager()
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


def _record(name, epoch):
    return {
        "tmux_name": name,
        "epoch": epoch,
        "hints": ["its name matches the auto-generated form"],
        "reason": "no_admissible_evidence",
    }


def _seed(tmp_path, records, rows=()):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as conn:
        with transaction(conn):
            for name, epoch, origin in rows:
                record_instance(
                    conn,
                    socket=SOCKET,
                    name=name,
                    epoch=epoch,
                    origin=origin,
                    now=STAMP,
                )
            if records is not None:
                set_meta(
                    conn,
                    META_SESSION_IMPORT_UNATTRIBUTED,
                    json.dumps(records, sort_keys=True),
                )


def _prompt(client):
    body = client.get("/api/v1/sessions/attribution-prompt").json()
    return body["state"], [s["tmux_name"] for s in body.get("sessions") or []]


def test_adopting_every_candidate_empties_the_prompt(tmp_path, monkeypatch):
    names = [
        "cloude_Test",
        "cloude_asd",
        "cloude_config-sync-tool-2",
        "cloude_scrolltest",
        "cloude_test pause",
    ]
    records = [_record(n, 1755000000 + i) for i, n in enumerate(names)]
    rows = [
        (n, 1755000000 + i, SESSION_ORIGIN_ADOPTED) for i, n in enumerate(names)
    ]
    _seed(tmp_path, records, rows)
    state, shown = _prompt(_client(tmp_path, monkeypatch))
    assert shown == []
    assert state == "none"


def test_adopting_some_leaves_only_the_rest(tmp_path, monkeypatch):
    records = [_record("cloude_a", 1), _record("cloude_b", 2)]
    _seed(
        tmp_path,
        records,
        [
            ("cloude_a", 1, SESSION_ORIGIN_ADOPTED),
            ("cloude_b", 2, SESSION_ORIGIN_OBSERVED),
        ],
    )
    state, shown = _prompt(_client(tmp_path, monkeypatch))
    assert shown == ["cloude_b"]
    assert state == "pending"


def test_a_row_proved_ours_by_a_rerun_also_leaves_the_prompt(
    tmp_path, monkeypatch
):
    _seed(
        tmp_path,
        [_record("cloude_a", 1)],
        [("cloude_a", 1, SESSION_ORIGIN_CREATED)],
    )
    assert _prompt(_client(tmp_path, monkeypatch)) == ("none", [])


def test_a_declined_row_is_gone_even_if_the_snapshot_still_lists_it(
    tmp_path, monkeypatch
):
    _seed(
        tmp_path,
        [_record("cloude_a", 1)],
        [("cloude_a", 1, SESSION_ORIGIN_OBSERVED)],
    )
    with closing(connect(db_path_for(tmp_path))) as conn:
        with transaction(conn):
            record_decline(
                conn, socket=SOCKET, name="cloude_a", epoch=1, now=STAMP
            )
    assert _prompt(_client(tmp_path, monkeypatch)) == ("none", [])


def test_an_unanswered_observed_row_still_asks(tmp_path, monkeypatch):
    _seed(
        tmp_path,
        [_record("cloude_a", 1)],
        [("cloude_a", 1, SESSION_ORIGIN_OBSERVED)],
    )
    assert _prompt(_client(tmp_path, monkeypatch)) == ("pending", ["cloude_a"])


def test_a_candidate_with_no_row_is_kept_not_silently_dropped(
    tmp_path, monkeypatch
):
    _seed(tmp_path, [_record("cloude_ghost", 1)], [])
    assert _prompt(_client(tmp_path, monkeypatch)) == (
        "pending",
        ["cloude_ghost"],
    )


def test_a_candidate_with_no_epoch_is_kept_not_silently_dropped(
    tmp_path, monkeypatch
):
    _seed(
        tmp_path,
        [_record("cloude_a", None)],
        [("cloude_a", 1, SESSION_ORIGIN_ADOPTED)],
    )
    assert _prompt(_client(tmp_path, monkeypatch)) == ("pending", ["cloude_a"])


def test_a_row_on_another_socket_does_not_answer_for_ours(
    tmp_path, monkeypatch
):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as conn:
        with transaction(conn):
            record_instance(
                conn,
                socket="other",
                name="cloude_a",
                epoch=1,
                origin=SESSION_ORIGIN_ADOPTED,
                now=STAMP,
            )
            set_meta(
                conn,
                META_SESSION_IMPORT_UNATTRIBUTED,
                json.dumps([_record("cloude_a", 1)], sort_keys=True),
            )
    assert _prompt(_client(tmp_path, monkeypatch)) == ("pending", ["cloude_a"])

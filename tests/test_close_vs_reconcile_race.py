
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import session_crud_routes
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.session_close_lifecycle import LIFECYCLE_SOURCE_CLOSED, mark_closed
from src.core.session_journal_observe import STATE_LIVE, instance_key
from src.core.session_lifecycle import reconcile_from_listing
from src.core.session_restore_offer import offer_candidates
from src.core.tmux_listing import TmuxListing
from src.core.trail_entry import utc_now

NAME = "carnivore_Orchard-Budgets"
EPOCH = 1790090835
UUID = "u-budgets"


@pytest.fixture
def state(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    with closing(connect(db_path_for(state))) as conn:
        _insert(conn)
    return state


def _insert(conn, **overrides) -> int:
    row = {
        "session_uuid": UUID,
        "origin": "created",
        "tmux_socket": "cloude",
        "tmux_name": NAME,
        "tmux_created_epoch": EPOCH,
        "working_dir": "/Users/x/proj",
        "lifecycle": "running",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    row.update(overrides)
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with transaction(conn):
        cur = conn.execute(
            f"INSERT INTO sessions ({cols}) VALUES ({marks})", list(row.values())
        )
    return int(cur.lastrowid)


def _reconcile_sees_it_gone(conn) -> None:
    reconcile_from_listing(conn, listing=TmuxListing.answered([]), socket="cloude")
    conn.commit()


def _row(conn, uuid: str = UUID) -> dict:
    return dict(
        conn.execute("SELECT * FROM sessions WHERE session_uuid = ?", (uuid,)).fetchone()
    )


def _offered(conn) -> list:
    rows = [dict(r) for r in conn.execute("SELECT * FROM sessions").fetchall()]
    journal = {
        "sessions": {
            instance_key(NAME, EPOCH): {
                "session_uuid": UUID,
                "tmux_name": NAME,
                "tmux_epoch": EPOCH,
                "state": STATE_LIVE,
            }
        }
    }
    return [c["session_uuid"] for c in offer_candidates(journal, rows, live_instances=set())]


def test_reconcile_first_then_close_still_records_the_close(state: Path) -> None:
    with closing(connect(db_path_for(state))) as conn:
        _reconcile_sees_it_gone(conn)
        assert _row(conn)["lifecycle_source"] == "tmux_missing"
        assert _offered(conn) == [UUID]

        moved = mark_closed(conn, socket="cloude", name=NAME, epoch=EPOCH)
        conn.commit()

        assert moved == 1
        row = _row(conn)
        assert (row["lifecycle"], row["lifecycle_source"]) == ("stopped", LIFECYCLE_SOURCE_CLOSED)
        assert row["archived_at"] is None
        assert _offered(conn) == []


def test_close_route_with_reconcile_inside_the_kill(state: Path, monkeypatch) -> None:
    events: list = []

    class Backend:
        tmux_session = NAME
        socket_name = "cloude"

        async def session_created_epoch(self) -> int:
            events.append("epoch")
            return EPOCH

    class Manager:
        async def destroy_session(self, session_id=None) -> None:
            events.append("destroy")
            with closing(connect(db_path_for(state))) as conn:
                _reconcile_sees_it_gone(conn)

    class LocalServers:
        async def clear_session(self, name: str) -> None:
            return None

    backend = Backend()
    app_state = SimpleNamespace(
        session_manager=Manager(),
        local_servers=LocalServers(),
        services=SimpleNamespace(
            registry=SimpleNamespace(get_backend=lambda sid: backend)
        ),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=app_state))
    monkeypatch.setattr(
        session_crud_routes, "settings", SimpleNamespace(get_state_dir=lambda: state)
    )

    asyncio.run(session_crud_routes.destroy_session(request, session_id="ses_x"))

    with closing(connect(db_path_for(state))) as conn:
        assert _row(conn)["lifecycle_source"] == LIFECYCLE_SOURCE_CLOSED
        assert _offered(conn) == []
    assert events == ["epoch", "destroy"]


def test_close_never_relabels_an_older_row_that_shares_the_name(state: Path) -> None:
    with closing(connect(db_path_for(state))) as conn:
        older = _insert(
            conn,
            session_uuid="u-older",
            tmux_created_epoch=EPOCH - 5000,
            lifecycle="stopped",
            lifecycle_source="tmux_missing",
        )
        mark_closed(conn, socket="cloude", name=NAME, epoch=EPOCH)
        conn.commit()
        assert _row(conn, "u-older")["lifecycle_source"] == "tmux_missing", older


@pytest.mark.parametrize("source", ["pane_dead", "slept_by_user", "closed_by_user"])
def test_close_leaves_every_other_stopped_source_alone(state: Path, source: str) -> None:
    with closing(connect(db_path_for(state))) as conn:
        conn.execute(
            "UPDATE sessions SET lifecycle = 'stopped', lifecycle_source = ?", (source,)
        )
        conn.commit()
        assert mark_closed(conn, socket="cloude", name=NAME, epoch=EPOCH) == 0
        assert _row(conn)["lifecycle_source"] == source


def test_without_an_epoch_only_a_running_row_moves(state: Path) -> None:
    with closing(connect(db_path_for(state))) as conn:
        _reconcile_sees_it_gone(conn)
        assert mark_closed(conn, socket="cloude", name=NAME) == 0
        assert _row(conn)["lifecycle_source"] == "tmux_missing"

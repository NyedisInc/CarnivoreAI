
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lsr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lsr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.session_instance_index import InstanceIndex, build_instance_index
from src.core.session_status_seed_read import read_instance_row
from tests.s7_helpers import migrated_connection

SOCKET = "cloude_pytest_seedcost"

INSTANCES = 4


class _CountingManager:

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self.opens = 0

    def _writable_datastore_connection(self):
        from src.core.db import connect

        self.opens += 1
        return connect(str(self._db_path), create=False)

    def _tmux_socket_name(self) -> str:
        return SOCKET


@pytest.fixture
def seeded_db(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    keys: List[tuple] = []
    with closing(migrated_connection(state)) as conn:
        for index in range(INSTANCES):
            name = f"cloude_seedcost_{index}"
            epoch = 1_700_000_000 + index
            keys.append((name, epoch))
            conn.execute(
                "INSERT INTO sessions ("
                "  session_uuid, origin, created_at, updated_at, working_dir, "
                "  tmux_socket, tmux_name, tmux_created_epoch, "
                "  activity_state, activity_state_at, claude_session_uuid"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"uuid-{index}",
                    "created",
                    "2026-09-10T00:00:00Z",
                    "2026-09-10T00:00:00Z",
                    f"/tmp/proj-{index}",
                    SOCKET,
                    name,
                    epoch,
                    f"state-{index}",
                    f"2026-09-10T0{index}:00:00Z",
                    f"conv-{index}",
                ),
            )
        conn.commit()
        db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    return db_path, keys


def _index_for(db_path: Path, names) -> InstanceIndex:
    from src.core.db import connect

    with closing(connect(str(db_path), create=False)) as conn:
        return build_instance_index(conn, socket=SOCKET, names=list(names))


def test_the_seed_row_read_opens_no_connection_when_the_pass_took_one(
    seeded_db,
):
    db_path, keys = seeded_db
    index = _index_for(db_path, [name for name, _ in keys])
    assert index.complete is True, (
        "the index must report that its query RAN, or the seam is "
        "required to fall back and this measurement is meaningless"
    )

    manager = _CountingManager(db_path)
    rows = [
        read_instance_row(manager, name, epoch, index=index)
        for name, epoch in keys
    ]

    assert manager.opens == 0, (
        f"the seed read opened the datastore {manager.opens} times for "
        f"{INSTANCES} sessions despite the pass having already fetched "
        "every one of those rows in a single query. Opening a connection "
        "per session inside a synchronous listing pass is blocking "
        "SQLite on the event loop, which the user feels as lag in the "
        "TERMINAL rather than as a slow list."
    )
    assert all(row is not None for row in rows), (
        "a cheaper read that stops finding the rows is not the fix"
    )


def test_the_bulk_read_and_the_per_row_read_agree_field_for_field(seeded_db):
    db_path, keys = seeded_db
    index = _index_for(db_path, [name for name, _ in keys])

    bulk_manager = _CountingManager(db_path)
    per_row_manager = _CountingManager(db_path)

    bulk: List[Optional[Dict[str, Any]]] = [
        read_instance_row(bulk_manager, name, epoch, index=index)
        for name, epoch in keys
    ]
    per_row: List[Optional[Dict[str, Any]]] = [
        read_instance_row(per_row_manager, name, epoch)
        for name, epoch in keys
    ]

    assert per_row_manager.opens == INSTANCES, (
        "the control did not exercise the per-row path it is controlling "
        f"for: it opened {per_row_manager.opens} connections for "
        f"{INSTANCES} rows"
    )
    assert bulk == per_row, (
        "reading the stored row once for the whole pass changed what the "
        "read says. The index may only change HOW MANY TIMES the row is "
        "fetched, never what the row means."
    )
    assert len({row["activity_state"] for row in bulk}) == INSTANCES


def test_an_index_that_could_not_be_built_falls_back_and_never_answers_none(
    seeded_db,
):
    db_path, keys = seeded_db
    name, epoch = keys[0]

    could_not_look = InstanceIndex()
    assert could_not_look.complete is False

    manager = _CountingManager(db_path)
    row = read_instance_row(manager, name, epoch, index=could_not_look)

    assert manager.opens == 1, (
        "an index that reports it could not be built must fall through "
        "to the per-row connection, which is exactly the behaviour every "
        "caller had before the index existed"
    )
    assert row is not None and row["activity_state"] == "state-0"


def test_a_complete_index_with_no_row_still_means_no_row(seeded_db):
    db_path, _keys = seeded_db
    index = _index_for(db_path, ["cloude_seedcost_not_a_real_one"])
    assert index.complete is True

    manager = _CountingManager(db_path)
    row = read_instance_row(
        manager, "cloude_seedcost_not_a_real_one", 1_700_000_999, index=index
    )

    assert row is None
    assert manager.opens == 0, (
        "a complete index answering 'no row' is a measurement, not a "
        "failure to look, so it must not cost a fallback connection"
    )


from __future__ import annotations

import ast
import os
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rec_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rec_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_SOURCE_IMPORT,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.tmux_listing import TmuxListing

SOCKET = "cloude"
MODULE_PATH = ROOT / "src" / "core" / "session_lifecycle.py"

WRITER_FUNCTION = "_reap_absent_instances"

ENTRY_FUNCTION = "reconcile_from_listing"


@pytest.fixture()
def conn(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection


def add_row(
    conn,
    *,
    uuid,
    name,
    epoch,
    lifecycle=SESSION_LIFECYCLE_RUNNING,
    socket=SOCKET,
    origin=SESSION_ORIGIN_OBSERVED,
    archived_at=None,
    adopted_at=None,
    tmux_session_id=None,
):
    cur = conn.execute(
        "INSERT INTO sessions (session_uuid, origin, adopted_at, tmux_socket, "
        "tmux_name, tmux_created_epoch, tmux_session_id, lifecycle, "
        "lifecycle_source, lifecycle_checked_at, last_seen_running_at, "
        "archived_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            uuid,
            origin,
            adopted_at,
            socket,
            name,
            epoch,
            tmux_session_id,
            lifecycle,
            SESSION_LIFECYCLE_SOURCE_IMPORT,
            "2026-08-18T00:00:00.000000Z",
            "2026-08-18T00:00:00.000000Z",
            archived_at,
            "2026-08-18T00:00:00.000000Z",
            "2026-08-18T00:00:00.000000Z",
        ),
    )
    return int(cur.lastrowid)


def row_by_uuid(conn, uuid):
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_uuid = ?", (uuid,)
    ).fetchone()
    assert row is not None, f"no row for {uuid}"
    return dict(row)


def live(*pairs):
    return TmuxListing.answered(
        [
            {"name": n, "created_at_epoch": e, "window_count": 1}
            for n, e in pairs
        ]
    )


class CountingConnection:

    def __init__(self, real):
        self._real = real
        self.statements = []

    def execute(self, sql, *args, **kwargs):
        self.statements.append(sql)
        return self._real.execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        self.statements.append(sql)
        return self._real.executemany(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)

    @property
    def writes(self):
        return [
            s
            for s in self.statements
            if not s.lstrip().upper().startswith(("SELECT", "PRAGMA"))
        ]


class ExplodingConnection:

    def __getattr__(self, item):
        raise AssertionError(
            f"the reconciler touched the database ({item!r}) on a branch "
            "that must never read or write it"
        )






def module_ast():
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"))


def function_named(tree, name):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not a top-level function any more")


def sql_literals(node):
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            text = " ".join(sub.value.split()).upper()
            if text.startswith(("UPDATE ", "INSERT ", "DELETE ", "REPLACE ")):
                out.append(text)
    return out

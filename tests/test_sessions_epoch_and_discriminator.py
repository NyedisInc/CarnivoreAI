
from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from typing import List

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.session_identity import RECORD_INSERTED, record_instance
from src.core.session_import import run_first_run_import
from src.core.session_import_mapping import _persisted_session_id, _stopped_epoch
from src.core.session_store import get_instance, owned_instances
from src.core.tmux_listing import TmuxListing
from src.core.tmux_listing_parse import resolve_ownership

SOCKET = "cloude"
REAL_EPOCH = 1755000000
LATER_EPOCH = 1787000000


@pytest.fixture()
def migrated_conn(tmp_path: Path):
    ensure_db_migrated(tmp_path, config_version=4, app_version="0.0.0-test")
    conn = connect(db_path_for(tmp_path))
    try:
        yield conn
    finally:
        conn.close()




def test_stopped_epoch_is_none_when_the_entry_records_none() -> None:
    assert _stopped_epoch({}) is None
    assert _stopped_epoch({"session_id": "abc"}) is None
    assert _stopped_epoch({"tmux_created_epoch": None}) is None
    assert _stopped_epoch({"tmux_created_epoch": "not-an-int"}) is None


def test_stopped_epoch_still_uses_a_recorded_epoch() -> None:
    assert _stopped_epoch({"tmux_created_epoch": REAL_EPOCH}) == REAL_EPOCH
    assert _stopped_epoch({"created_at_epoch": REAL_EPOCH}) == REAL_EPOCH
    assert _stopped_epoch({"tmux_created_epoch": "1755000000"}) == REAL_EPOCH


def test_null_epoch_row_never_becomes_an_ownership_opinion(migrated_conn) -> None:
    with migrated_conn:
        result = record_instance(
            migrated_conn,
            socket=SOCKET,
            name="cloude_work",
            epoch=None,
            origin="created",
            lifecycle="stopped",
        )
    assert result.outcome == RECORD_INSERTED

    stored = migrated_conn.execute(
        "SELECT tmux_created_epoch FROM sessions WHERE tmux_name = ?",
        ("cloude_work",),
    ).fetchone()
    assert stored[0] is None, "the epoch must be stored as SQL NULL"

    assert owned_instances(migrated_conn, socket=SOCKET) == set(), (
        "a row with no recorded epoch must not reach the ownership "
        "resolver at all"
    )


def test_null_epoch_row_does_not_disown_a_later_real_session(
    migrated_conn,
) -> None:
    with migrated_conn:
        record_instance(
            migrated_conn,
            socket=SOCKET,
            name="cloude_work",
            epoch=None,
            origin="created",
            lifecycle="stopped",
        )

    owned = owned_instances(migrated_conn, socket=SOCKET)
    verdict = resolve_ownership(
        "cloude_work", LATER_EPOCH, owned, {"cloude_work"}, prefix="cloude_"
    )
    assert verdict is True, (
        "with no epoch-keyed opinion stored, the legacy name tier must be "
        "reachable; a fabricated epoch used to pre-empt it with a False"
    )


def test_a_real_stored_epoch_still_produces_the_negative(migrated_conn) -> None:
    with migrated_conn:
        record_instance(
            migrated_conn,
            socket=SOCKET,
            name="cloude_work",
            epoch=REAL_EPOCH,
            origin="created",
            lifecycle="stopped",
        )

    owned = owned_instances(migrated_conn, socket=SOCKET)
    assert owned == {("cloude_work", REAL_EPOCH)}
    assert resolve_ownership(
        "cloude_work", LATER_EPOCH, owned, {"cloude_work"}, prefix="cloude_"
    ) is False


def test_get_instance_with_a_none_epoch_matches_nothing(migrated_conn) -> None:
    with migrated_conn:
        record_instance(
            migrated_conn,
            socket=SOCKET,
            name="cloude_work",
            epoch=REAL_EPOCH,
            origin="created",
        )
    assert get_instance(
        migrated_conn, socket=SOCKET, name="cloude_work", epoch=None
    ) is None


def test_two_null_epoch_rows_do_not_collide(migrated_conn) -> None:
    with migrated_conn:
        first = record_instance(
            migrated_conn, socket=SOCKET, name="cloude_work", epoch=None,
            origin="observed", lifecycle="stopped",
        )
        second = record_instance(
            migrated_conn, socket=SOCKET, name="cloude_work", epoch=None,
            origin="observed", lifecycle="stopped",
        )
    assert first.outcome == RECORD_INSERTED
    assert second.outcome == RECORD_INSERTED
    assert first.session_uuid != second.session_uuid




def test_persisted_session_id_reads_only_the_tmux_namespace() -> None:
    assert _persisted_session_id({"tmux_session_id": "$3"}) == "$3"
    assert _persisted_session_id({"session_id": "abc"}) is None
    assert _persisted_session_id({"id": "abc"}) is None
    assert _persisted_session_id({}) is None
    assert _persisted_session_id({"tmux_session_id": "   "}) is None


def test_step_five_records_a_known_discriminator(migrated_conn) -> None:
    listing = TmuxListing.answered([], reason=None, detail="no live sessions")
    with migrated_conn:
        migrated_conn.execute("BEGIN IMMEDIATE")
        run_first_run_import(
            migrated_conn,
            listing=listing,
            owned_tmux_names={"cloude_known"},
            persisted_sessions=[
                {
                    "tmux_session": "cloude_known",
                    "session_id": "app-side-id",
                    "tmux_session_id": "$12",
                    "tmux_created_epoch": REAL_EPOCH,
                },
            ],
            socket=SOCKET,
        )
        migrated_conn.execute("COMMIT")

    row = migrated_conn.execute(
        "SELECT tmux_session_id, legacy_session_id, tmux_created_epoch "
        "FROM sessions WHERE tmux_name = ?",
        ("cloude_known",),
    ).fetchone()
    assert row[0] == "$12", "the tmux discriminator must be persisted"
    assert row[1] == "app-side-id", "the app id belongs in legacy_session_id"
    assert row[2] == REAL_EPOCH


def test_step_five_null_discriminator_is_measured_not_forgotten(
    migrated_conn,
) -> None:
    listing = TmuxListing.answered([], reason=None, detail="no live sessions")
    with migrated_conn:
        migrated_conn.execute("BEGIN IMMEDIATE")
        run_first_run_import(
            migrated_conn,
            listing=listing,
            owned_tmux_names={"cloude_work"},
            persisted_sessions=[
                {"tmux_session": "cloude_work", "session_id": "abc"},
            ],
            socket=SOCKET,
        )
        migrated_conn.execute("COMMIT")

    row = migrated_conn.execute(
        "SELECT tmux_session_id, tmux_created_epoch, legacy_session_id "
        "FROM sessions WHERE tmux_name = ?",
        ("cloude_work",),
    ).fetchone()
    assert row[0] is None, "no tmux id was recorded, so NULL is the truth"
    assert row[1] is None, "no epoch was recorded, so NULL - never a 0"
    assert row[2] == "abc"

    assert owned_instances(migrated_conn, socket=SOCKET) == set(), (
        "the row must not become an epoch-keyed ownership opinion"
    )


def test_step_five_passes_session_id_structurally() -> None:
    source = (ROOT / "src" / "core" / "session_import.py").read_text()
    tree = ast.parse(source)

    calls_without_session_id: List[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != "record_instance":
            continue
        if not any(kw.arg == "session_id" for kw in node.keywords):
            calls_without_session_id.append(node.lineno)

    assert calls_without_session_id == [], (
        "every record_instance call in the import must pass session_id "
        "explicitly, so a NULL discriminator is a measured absence rather "
        f"than a forgotten argument. Missing at lines: "
        f"{calls_without_session_id}"
    )




def test_no_source_file_deletes_a_sessions_row() -> None:
    migration_steps = "core/db_steps.py"
    non_reaper_deleters = {
        "core/companion_shell/close.py",
        "core/federation/ddl_peer_sessions.py",
        "core/federation/shadow_rows.py",
        "core/library_cleanup/sessions.py",
        "core/pack/migrate/manifest.py",
        "core/pack/move/receive.py",
    }

    offenders: List[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        rel = str(path.relative_to(ROOT / "src"))
        if rel == migration_steps or rel in non_reaper_deleters:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))

        docstring_nodes = set()
        for node in ast.walk(tree):
            if isinstance(
                node,
                (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ):
                body = getattr(node, "body", None)
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    docstring_nodes.add(id(body[0].value))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str) or id(node) in docstring_nodes:
                continue
            if "delete from sessions" in node.value.lower():
                offenders.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}"
                )

    assert offenders == [], (
        "a sessions reaper now exists. Update the KNOWN GAP section of "
        "src/core/session_store.py's module docstring, and make sure the "
        "reaper is gated on TmuxListing.ok being True - reaping against "
        f"ok=False would delete the user's whole history. Found in: "
        f"{offenders}"
    )


def test_session_store_documents_the_missing_repair_path() -> None:
    import src.core.session_store as session_store

    doc = session_store.__doc__ or ""
    assert "DELETE" in doc.upper()
    assert "reaper" in doc.lower(), (
        "the intended repair path must be described, not merely the gap"
    )
    assert "ok=True" in doc, (
        "the load-bearing constraint on any future reaper must be stated"
    )


def test_the_only_delete_lives_in_the_v9_merge() -> None:
    path = ROOT / "src" / "core" / "db_steps.py"
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))

    allowed = "_v9_merge_rename_splits"
    stray: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == allowed:
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Constant)
                and isinstance(inner.value, str)
                and "delete from sessions" in inner.value.lower()
            ):
                stray.append(f"{node.name}:{inner.lineno}")

    assert stray == [], (
        "a sessions DELETE appeared outside the v9 merge. The file-level "
        "exemption in test_no_source_file_deletes_a_sessions_row covers "
        f"exactly one function, not the whole file. Found in: {stray}"
    )

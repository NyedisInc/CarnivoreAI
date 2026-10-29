
from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for, get_meta, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    META_IMPORTED_FROM_JSON_AT,
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_ORIGIN_ADOPTED,
    SESSION_ORIGIN_CREATED,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.session_identity import (
    RECORD_REFUSED_INSTANCE_MISMATCH,
    adopt_instance,
    record_instance,
)
from src.core.session_import import (
    IMPORT_COMPLETED,
    IMPORT_PENDING_LISTING_UNAVAILABLE,
    ImportLatchUnreadable,
    run_first_run_import,
)
from src.core.session_store import count_sessions, list_sessions
from src.core.tmux_listing_parse import parse_listing_row, resolve_ownership
from src.core.tmux_listing import (
    TmuxListing,
    classify_listing_failure,
    looks_like_no_server,
)


@dataclass
class FakeProject:

    name: str
    path: str
    description: Optional[str] = None
    agent_type: str = "claude"


@pytest.fixture()
def conn(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection


def _live(name, epoch, working_dir=None):
    row = {"name": name, "created_at_epoch": epoch, "window_count": 1}
    if working_dir is not None:
        row["working_dir"] = working_dir
    return row



REAL_TMUX_STDERR_THAT_IS_NOT_NO_SERVER = (
    "error connecting to /tmp/advt/noperm/sock2 (Permission denied)",
    "error connecting to /tmp/advt/noperm/sock (Socket operation on non-socket)",
    "error connecting to /very/long/path/sock (File name too long)",
)


@pytest.mark.parametrize("stderr_text", REAL_TMUX_STDERR_THAT_IS_NOT_NO_SERVER)
def test_defect_probe_failure_misclassified_as_zero_sessions(stderr_text):
    assert looks_like_no_server(stderr_text) is False
    listing = classify_listing_failure(1, stderr_text)
    assert listing.ok is False
    assert listing.sessions == []
    assert listing.reason != "no_server"


def test_defect_latch_stamped_after_unreadable_socket(conn):
    listing = classify_listing_failure(
        1, "error connecting to /tmp/x/sock (Permission denied)"
    )
    result = run_first_run_import(conn, listing=listing)
    assert result.outcome == IMPORT_PENDING_LISTING_UNAVAILABLE
    assert result.pending is True
    assert result.sessions_imported == 0
    assert count_sessions(conn) == 0
    assert get_meta(conn, META_IMPORTED_FROM_JSON_AT) is None
    notice = result.home_screen_notice()
    assert notice is not None and "PENDING" in notice

    second = run_first_run_import(
        conn,
        listing=TmuxListing.answered([_live("cloude_work", 1755000000)]),
        owned_tmux_names={"cloude_work"},
    )
    assert second.outcome == IMPORT_COMPLETED
    assert count_sessions(conn) == 1
    assert list_sessions(conn)[0]["tmux_name"] == "cloude_work"




def _parse_listing_line(line, owned_instances=None, owned_names=None):
    row = parse_listing_row(line)
    if row is None:
        return None
    return {
        "name": row["name"],
        "created_at_epoch": row["created_at_epoch"],
        "owned": resolve_ownership(
            row["name"], row["created_at_epoch"], owned_instances, owned_names
        ),
    }


def test_defect_pipe_in_tmux_name_forges_the_instance_triple():
    real_tmux_line = "victim|1755000000|1|1787070480|1"
    owned_from_db = {("victim", 1755000000)}
    row = _parse_listing_line(real_tmux_line, owned_instances=owned_from_db)
    assert row is None, "the forged line still parses"

    honest = _parse_listing_line(
        "$7|1787070480|1|victim|1755000000|1", owned_instances=owned_from_db
    )
    assert honest["name"] == "victim|1755000000|1"
    assert honest["created_at_epoch"] == 1787070480
    assert honest["owned"] is False


def test_defect_sanitize_tmux_name_permits_the_delimiter():
    from src.core.session_manager import _sanitize_tmux_name

    assert _sanitize_tmux_name("api|prod") == "api_prod"
    assert "|" not in _sanitize_tmux_name("a|b|c")




def test_defect_legacy_wildcard_epoch_defeats_the_instance_key():
    owned_from_db = {("cloude_work", 1755000000)}
    legacy_names = {"cloude_work"}

    stranger = _parse_listing_line(
        "$9|1787070999|1|cloude_work",
        owned_instances=owned_from_db,
        owned_names=legacy_names,
    )
    assert stranger["created_at_epoch"] == 1787070999
    assert stranger["owned"] is False

    wildcard = _parse_listing_line(
        "$9|1787070999|1|cloude_work",
        owned_instances={("cloude_work", None)},
    )
    assert wildcard["owned"] is False

    real = _parse_listing_line(
        "$2|1755000000|1|cloude_work", owned_instances=owned_from_db
    )
    assert real["owned"] is True




def test_defect_adoption_transfers_to_a_stranger_on_a_running_row(conn):
    with transaction(conn):
        record_instance(
            conn,
            socket="cloude",
            name="cloude_work",
            epoch=1755000000,
            origin=SESSION_ORIGIN_CREATED,
            lifecycle=SESSION_LIFECYCLE_RUNNING,
            session_id="$3",
        )
        adopt_instance(
            conn, socket="cloude", name="cloude_work", epoch=1755000000,
            now="2026-08-18T00:00:00Z",
        )
    before = list_sessions(conn)[0]
    assert before["origin"] == SESSION_ORIGIN_ADOPTED

    with transaction(conn):
        result = record_instance(
            conn,
            socket="cloude",
            name="cloude_work",
            epoch=1755000000,
            origin=SESSION_ORIGIN_OBSERVED,
            lifecycle=SESSION_LIFECYCLE_RUNNING,
            session_id="$9",
        )
    assert result.outcome == RECORD_REFUSED_INSTANCE_MISMATCH
    assert result.refused is True
    after = list_sessions(conn)[0]
    assert after["session_uuid"] == before["session_uuid"]
    assert after["origin"] == SESSION_ORIGIN_ADOPTED
    assert after["adopted_at"] == "2026-08-18T00:00:00Z"


def test_the_live_listing_path_ALWAYS_supplies_the_discriminator():
    assert parse_listing_row("$0|1|1|a")["session_id"] == "$0"
    assert parse_listing_row("1|1|a") is None
    assert parse_listing_row("x|1|1|a") is None
    assert parse_listing_row("|1755000000|1|a") is None


def test_defect_adopt_instance_can_claim_a_dead_session(conn):
    with transaction(conn):
        record_instance(
            conn, socket="cloude", name="dead", epoch=1755000000,
            origin=SESSION_ORIGIN_OBSERVED,
            lifecycle=SESSION_LIFECYCLE_STOPPED,
        )
        claimed = adopt_instance(
            conn, socket="cloude", name="dead", epoch=1755000000
        )
    assert claimed is False
    row = list_sessions(conn)[0]
    assert row["origin"] == SESSION_ORIGIN_OBSERVED
    assert row["adopted_at"] is None




def test_defect_persisted_owned_session_imports_as_observed(conn):
    result = run_first_run_import(
        conn,
        listing=TmuxListing.answered([]),
        owned_tmux_names={"cloude_mine"},
        persisted_sessions=[
            {"tmux_session": "cloude_mine", "id": "sess-1",
             "agent_type": "claude", "tmux_created_epoch": 1755000000},
        ],
    )
    assert result.outcome == IMPORT_COMPLETED
    row = list_sessions(conn)[0]
    assert row["tmux_name"] == "cloude_mine"
    assert row["lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert row["origin"] == SESSION_ORIGIN_CREATED




def test_defect_import_hardcodes_the_default_socket(conn):
    run_first_run_import(
        conn,
        listing=TmuxListing.answered([_live("cloude_a", 1755000000)]),
        owned_tmux_names={"cloude_a"},
        socket="mysock",
    )
    import inspect

    import src.main as main_mod
    from src.core.session_store import owned_instances

    main_src = inspect.getsource(main_mod)
    call = main_src[main_src.index("run_first_run_import("):]
    call = call[: call.index("\n                    )")]
    assert "socket=" in call
    assert "tmux_socket_name()" in call

    assert list_sessions(conn)[0]["tmux_socket"] == "mysock"
    assert owned_instances(conn, socket="mysock") == {("cloude_a", 1755000000)}
    assert owned_instances(conn, socket="some-other-socket") == set()




def test_defect_corrupt_result_blob_reruns_the_import(conn):
    from src.core.db import set_meta
    from src.core.db_models import META_IMPORTED_FROM_JSON_RESULT
    from src.core.session_import import sessions_stage_done

    with transaction(conn):
        run_first_run_import(
            conn, listing=TmuxListing.answered([]),
        )
    assert sessions_stage_done(conn) is True

    with transaction(conn):
        set_meta(conn, META_IMPORTED_FROM_JSON_RESULT, "{not json")

    with pytest.raises(ImportLatchUnreadable):
        sessions_stage_done(conn)

    with pytest.raises(ImportLatchUnreadable):
        with transaction(conn):
            run_first_run_import(
                conn, listing=TmuxListing.answered([]),
            )

    assert get_meta(conn, META_IMPORTED_FROM_JSON_RESULT) == "{not json"




def test_defect_ast_proof_misses_the_guard_that_actually_latches(tmp_path):
    import ast

    src = (ROOT / "src" / "core" / "session_import.py").read_text()

    def _structural_ok(source: str) -> bool:
        tree = ast.parse(source)
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if func.name == "_latch_sessions_stage":
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None) or getattr(
                    node.func, "attr", None
                )
                if name == "_merge_result_blob":
                    for sub in ast.walk(node):
                        if getattr(sub, "id", None) == "RESULT_KEY_SESSIONS_STAGE":
                            return False
                if name == "set_meta":
                    for arg in node.args:
                        if getattr(arg, "id", None) == "META_IMPORTED_FROM_JSON_AT":
                            return False
        return True

    assert _structural_ok(src) is True

    hoist = (
        "    # --- step 3: THE GATE ---"
        "-----------------------------------------\n"
        "    _merge_result_blob(conn, {RESULT_KEY_SESSIONS_STAGE: stamp})\n"
    )
    marker = "    # --- step 3: THE GATE ------------------------------------------------\n"
    assert marker in src
    mutant = src.replace(marker, hoist, 1)

    assert _structural_ok(mutant) is False, (
        "the hoisted-blob mutation is STILL invisible to the structural "
        "proof; this is the mutation that latched the import shut "
        "permanently while every reader said it had never completed"
    )

    import json

    from src.core.db import set_meta
    from src.core.db_models import META_IMPORTED_FROM_JSON_RESULT
    from src.core.session_import import (
        RESULT_KEY_SESSIONS_STAGE,
        sessions_stage_done,
    )

    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as c:
        with transaction(c):
            blocked = run_first_run_import(
                c,
                listing=TmuxListing.answered([_live("cloude_work", 1755000000)]),
                owned_tmux_names={"cloude_work"},
            )
        assert blocked.outcome == IMPORT_COMPLETED
        assert count_sessions(c) == 1

        assert sessions_stage_done(c) is True
        assert get_meta(c, META_IMPORTED_FROM_JSON_AT) is not None
        blob = json.loads(get_meta(c, META_IMPORTED_FROM_JSON_RESULT))
        assert blob[RESULT_KEY_SESSIONS_STAGE] == get_meta(
            c, META_IMPORTED_FROM_JSON_AT
        ), "the operative latch key and the reported one disagree"

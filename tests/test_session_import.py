
from __future__ import annotations

import ast
import os
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
    META_SESSION_IMPORT_PENDING_REASON,
    SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    SESSION_ATTRIBUTION_NONE,
    SESSION_ATTRIBUTION_UNKNOWN,
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_ORIGIN_ADOPTED,
    SESSION_ORIGIN_CREATED,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.session_import import (
    IMPORT_ALREADY_DONE,
    IMPORT_COMPLETED,
    IMPORT_PENDING_LISTING_UNAVAILABLE,
    attribute_working_dir,
    run_first_run_import,
)
from src.core.session_store import count_sessions, list_sessions
from src.core.tmux_listing import (
    REASON_NO_SERVER,
    REASON_TIMEOUT,
    REASON_TMUX_MISSING,
    TmuxListing,
)

SESSION_IMPORT_PATH = ROOT / "src" / "core" / "session_import.py"


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


def _run(conn, listing, **kwargs):
    from src.core.project_store import import_from_config

    seed = kwargs.pop("projects", None) or []
    with transaction(conn):
        if seed:
            import_from_config(conn, seed)
        return run_first_run_import(conn, listing=listing, **kwargs)




@pytest.mark.parametrize(
    "reason", [REASON_TIMEOUT, REASON_TMUX_MISSING, "exit_2", "probe_error"]
)
def test_a_failed_probe_imports_nothing_and_LEAVES_THE_LATCH_UNSET(conn, reason):
    result = _run(conn, TmuxListing.unavailable(reason))

    assert result.outcome == IMPORT_PENDING_LISTING_UNAVAILABLE
    assert result.pending is True
    assert result.sessions_imported == 0
    assert count_sessions(conn) == 0, "a failed probe wrote session rows"
    assert get_meta(conn, META_IMPORTED_FROM_JSON_AT) is None, (
        "THE LATCH WAS STAMPED ON A FAILED PROBE. The import can never "
        "run again on this install and the user's session history is gone"
    )
    assert result.listing_reason == reason
    assert get_meta(conn, META_SESSION_IMPORT_PENDING_REASON) == reason
    notice = result.home_screen_notice()
    assert notice is not None and "PENDING" in notice and reason in notice


def test_a_later_successful_run_completes_the_import(conn):
    first = _run(conn, TmuxListing.unavailable(REASON_TIMEOUT))
    assert first.pending is True
    assert count_sessions(conn) == 0

    second = _run(
        conn,
        TmuxListing.answered([_live("cloude_a", 1000), _live("b", 2000)]),
        owned_tmux_names={"cloude_a"},
    )

    assert second.outcome == IMPORT_COMPLETED
    assert second.sessions_imported == 2
    assert count_sessions(conn) == 2
    assert get_meta(conn, META_IMPORTED_FROM_JSON_AT) is not None


def test_NO_CODE_PATH_STAMPS_THE_LATCH_ON_THE_FAILED_PROBE_BRANCH():
    source = SESSION_IMPORT_PATH.read_text()
    tree = ast.parse(source)

    latch_helper = "_latch_sessions_stage"

    def _enclosing_function(target):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(inner is target for inner in ast.walk(node)):
                    return node.name
        return None

    latch_writes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name == "set_meta":
            for arg in node.args:
                if getattr(arg, "id", None) == "META_IMPORTED_FROM_JSON_AT" or (
                    getattr(arg, "value", None) == "imported_from_json_at"
                ):
                    latch_writes.append(("imported_from_json_at", node.lineno))
        if name == "_merge_result_blob":
            for sub in ast.walk(node):
                if getattr(sub, "id", None) == "RESULT_KEY_SESSIONS_STAGE" or (
                    getattr(sub, "value", None) == "sessions_imported_at"
                ):
                    latch_writes.append(("sessions_imported_at", node.lineno))

    assert latch_writes, "found no latch writes at all - has the module moved?"
    for key, lineno in latch_writes:
        owner = _enclosing_function(
            next(
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.Call) and n.lineno == lineno
            )
        )
        assert owner == latch_helper, (
            f"the latch key {key!r} is written at line {lineno} inside "
            f"{owner!r}, not inside {latch_helper!r}. Every write that "
            "sessions_stage_done() can observe must live in the one "
            "helper, or a mutation can latch the import shut from a path "
            "this test does not constrain"
        )

    allowed_latchers = {"run_first_run_import", "_rerun_promote_only"}
    rerun_helper = "_rerun_promote_only"

    def _sites(fn_name):
        return [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == fn_name
        ]

    all_latch_sites = _sites(latch_helper)
    assert all_latch_sites, f"found no call to {latch_helper} at all"
    owners = {}
    for lineno in all_latch_sites:
        owner = _enclosing_function(
            next(
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.Call) and n.lineno == lineno
            )
        )
        owners.setdefault(owner, []).append(lineno)
    assert set(owners) <= allowed_latchers, (
        f"{latch_helper} is called from {sorted(set(owners) - allowed_latchers)}, "
        f"which is not one of the functions allowed to mark the import "
        f"complete ({sorted(allowed_latchers)})"
    )

    call_sites = owners.get("run_first_run_import", [])
    assert len(call_sites) == 1, (
        f"expected exactly ONE call to {latch_helper} inside "
        f"run_first_run_import, found {len(call_sites)} at lines "
        f"{call_sites}. Every extra one is a path that can mark the "
        "import complete without having done it"
    )

    rerun_sites = _sites(rerun_helper)
    assert len(rerun_sites) == 1, (
        f"expected exactly ONE call to {rerun_helper}, found {rerun_sites}"
    )
    rerun_owner = _enclosing_function(
        next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and n.lineno == rerun_sites[0]
        )
    )
    assert rerun_owner == "run_first_run_import", (
        f"{rerun_helper} is called from {rerun_owner!r}; it latches the "
        "import, so it must only be reachable from the guarded path"
    )

    gates = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.UnaryOp)
            and isinstance(test.op, ast.Not)
            and getattr(test.operand, "attr", None) == "ok"
        ):
            returns = any(
                isinstance(inner, ast.Return) for inner in ast.walk(node)
            )
            assert returns, "the listing.ok gate does not return"
            gates.append((node.lineno, node.end_lineno))

    assert len(gates) == 1, f"expected one listing.ok gate, found {gates}"
    gate_start, gate_end = gates[0]
    assert call_sites[0] > gate_end, (
        f"the latch call is at line {call_sites[0]}, which is NOT after "
        f"the failed-probe gate ending at line {gate_end}. It is "
        "reachable before the probe has been shown to have succeeded"
    )
    assert rerun_sites[0] > gate_end, (
        f"the re-run helper is called at line {rerun_sites[0]}, which is "
        f"NOT after the failed-probe gate ending at line {gate_end}. It "
        "latches, so calling it above the gate would mark the import "
        "complete on a probe that never answered"
    )

    gate_body = "\n".join(source.splitlines()[gate_start - 1:gate_end])
    assert "record_instance" not in gate_body, (
        "the failed-probe branch writes session rows"
    )


def test_the_ast_proof_KILLS_the_hoisted_blob_mutation():
    source = SESSION_IMPORT_PATH.read_text()
    marker = (
        "    # --- step 3: THE GATE ---------------------------------------"
        "---------\n"
    )
    assert marker in source, "the gate marker moved; update this mutation"
    mutant = source.replace(
        marker,
        "    _merge_result_blob(conn, {RESULT_KEY_SESSIONS_STAGE: stamp})\n"
        + marker,
        1,
    )
    tree = ast.parse(mutant)

    offenders = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if func.name == "_latch_sessions_stage":
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", None) != "_merge_result_blob":
                continue
            for sub in ast.walk(node):
                if getattr(sub, "id", None) == "RESULT_KEY_SESSIONS_STAGE":
                    offenders.append((func.name, node.lineno))

    assert offenders, (
        "the hoisted-blob mutant was NOT detected. This is the exact "
        "mutation that walked past the previous version of the AST proof "
        "and latched the import shut permanently"
    )


def test_pending_notice_is_absent_on_every_non_pending_outcome(conn):
    completed = _run(conn, TmuxListing.answered([]))
    assert completed.outcome == IMPORT_COMPLETED
    assert completed.home_screen_notice() is None

    again = _run(conn, TmuxListing.answered([]))
    assert again.outcome == IMPORT_ALREADY_DONE
    assert again.home_screen_notice() is None


def test_no_server_is_a_real_answer_of_zero_and_DOES_complete(conn):
    result = _run(conn, TmuxListing.answered([], reason=REASON_NO_SERVER))
    assert result.outcome == IMPORT_COMPLETED
    assert get_meta(conn, META_IMPORTED_FROM_JSON_AT) is not None




def test_importing_twice_with_ok_true_does_not_duplicate_rows(conn):
    listing = TmuxListing.answered([_live("cloude_a", 1000), _live("b", 2000)])
    first = _run(conn, listing, owned_tmux_names={"cloude_a"})
    assert first.sessions_imported == 2

    second = _run(conn, listing, owned_tmux_names={"cloude_a"})
    assert second.outcome == IMPORT_ALREADY_DONE
    assert second.sessions_imported == 0
    assert count_sessions(conn) == 2




def test_origin_is_created_only_when_the_name_is_in_the_owned_set(conn):
    _run(
        conn,
        TmuxListing.answered([_live("mine", 1000), _live("theirs", 2000)]),
        owned_tmux_names={"mine"},
    )
    by_name = {row["tmux_name"]: row for row in list_sessions(conn)}
    assert by_name["mine"]["origin"] == SESSION_ORIGIN_CREATED
    assert by_name["theirs"]["origin"] == SESSION_ORIGIN_OBSERVED


def test_NOTHING_is_ever_imported_as_adopted(conn):
    _run(
        conn,
        TmuxListing.answered([_live("a", 1), _live("b", 2), _live("c", 3)]),
        owned_tmux_names={"a"},
        persisted_sessions=[
            {"tmux_session": "b", "id": "adopted:b", "agent_type": "claude"},
            {"tmux_session": "gone", "id": "adopted:gone"},
        ],
    )
    origins = {row["origin"] for row in list_sessions(conn)}
    assert SESSION_ORIGIN_ADOPTED not in origins, (
        f"the import claimed an adoption it has no evidence for: {origins}"
    )
    assert origins == {SESSION_ORIGIN_CREATED, SESSION_ORIGIN_OBSERVED}
    assert all(row["adopted_at"] is None for row in list_sessions(conn))


def test_a_persisted_session_with_no_live_tmux_row_becomes_RECENT(conn):
    result = _run(
        conn,
        TmuxListing.answered([_live("live", 1000)]),
        persisted_sessions=[
            {
                "tmux_session": "dead",
                "id": "sess-123",
                "agent_type": "codex",
                "pinned_theme": "dracula",
            }
        ],
    )
    by_name = {row["tmux_name"]: row for row in list_sessions(conn)}
    assert by_name["live"]["lifecycle"] == SESSION_LIFECYCLE_RUNNING
    assert by_name["dead"]["lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert by_name["dead"]["agent_type"] == "codex"
    assert by_name["dead"]["pinned_theme"] == "dracula"
    assert by_name["dead"]["legacy_session_id"] == "sess-123"
    assert result.unmatched == [
        {"tmux_session": "dead", "reason": "no_live_tmux_row"}
    ]




def test_an_unprobeable_working_dir_is_unknown_and_never_guessed(conn):
    _run(
        conn,
        TmuxListing.answered([_live("no-cwd", 1000)]),
        projects=[FakeProject(name="p", path="/tmp/p")],
    )
    row = list_sessions(conn)[0]
    assert row["project_attribution"] == SESSION_ATTRIBUTION_UNKNOWN
    assert row["project_id"] is None


def test_attribution_picks_the_DEEPEST_matching_root():
    roots = {"/a": 1, "/a/b": 2}
    assert attribute_working_dir("/a/b/c", roots) == (
        2, SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    )
    assert attribute_working_dir("/a/x", roots) == (
        1, SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    )
    assert attribute_working_dir("/a/bc", roots) == (
        1, SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    )
    assert attribute_working_dir("/elsewhere", roots) == (
        None, SESSION_ATTRIBUTION_NONE,
    )
    assert attribute_working_dir(None, roots) == (
        None, SESSION_ATTRIBUTION_UNKNOWN,
    )
    assert attribute_working_dir("", roots) == (
        None, SESSION_ATTRIBUTION_UNKNOWN,
    )


def test_a_probed_working_dir_attributes_to_its_project(conn):
    _run(
        conn,
        TmuxListing.answered([_live("a", 1000, working_dir="/tmp/p/sub")]),
        projects=[FakeProject(name="p", path="/tmp/p")],
    )
    row = list_sessions(conn)[0]
    assert row["project_attribution"] == SESSION_ATTRIBUTION_DERIVED_DEEPEST
    assert row["project_id"] is not None


def test_the_working_dir_probe_callback_is_used_when_the_row_lacks_one(conn):
    _run(
        conn,
        TmuxListing.answered([_live("a", 1), _live("b", 2)]),
        projects=[FakeProject(name="p", path="/tmp/p")],
        working_dir_probe=lambda name: "/tmp/p" if name == "a" else None,
    )
    by_name = {row["tmux_name"]: row for row in list_sessions(conn)}
    assert by_name["a"]["project_attribution"] == (
        SESSION_ATTRIBUTION_DERIVED_DEEPEST
    )
    assert by_name["b"]["project_attribution"] == SESSION_ATTRIBUTION_UNKNOWN




def test_an_epoch_collision_during_import_is_recorded_not_swallowed(conn):
    _run(conn, TmuxListing.answered([_live("foo", 1000)]))
    with transaction(conn):
        conn.execute(
            "UPDATE sessions SET lifecycle = ? WHERE tmux_name = 'foo'",
            (SESSION_LIFECYCLE_STOPPED,),
        )
        conn.execute(
            "UPDATE meta SET value = json_remove(value, '$.sessions_imported_at') "
            "WHERE key = 'imported_from_json_result'"
        )
        conn.execute("DELETE FROM meta WHERE key = ?", (META_IMPORTED_FROM_JSON_AT,))

    result = _run(conn, TmuxListing.answered([_live("foo", 1000)]))
    assert len(result.refusals) == 1
    assert result.refusals[0]["tmux_name"] == "foo"
    assert result.refusals[0]["tmux_created_epoch"] == 1000
    assert count_sessions(conn) == 1


from __future__ import annotations

import ast
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
from src.core.tmux_listing import classify_listing_failure
from src.core.tmux_stderr import (
    LISTING_ENV_OVERRIDES,
    STDERR_CONNECT_FAILED,
    STDERR_NO_SERVER,
    STDERR_UNRECOGNISED,
    classify_tmux_stderr,
    listing_env,
)
from src.core.tmux_listing_parse import (
    LINE_BOUNDARY_CHARS,
    name_has_line_boundary,
    parse_listing_row,
    resolve_ownership,
    split_listing_rows,
)

TMUX_ACCEPTED_BOUNDARIES = ("\x85", " ", " ")

REAL_EPOCH = 1755000000




def test_python_and_tmux_disagree_about_line_boundaries() -> None:
    for char in TMUX_ACCEPTED_BOUNDARIES:
        assert len(f"x{char}y".splitlines()) == 2, (
            f"{char!r} is no longer a Python line boundary; the row "
            "delimiter analysis needs redoing"
        )
        assert char in LINE_BOUNDARY_CHARS


@pytest.mark.parametrize("boundary", TMUX_ACCEPTED_BOUNDARIES)
def test_forged_payload_yields_exactly_one_row(boundary: str) -> None:
    name = f"pwn{boundary}$99|{REAL_EPOCH}|1|cloude_work"
    stdout_text = f"$7|1787000000|1|{name}\n"

    assert len(stdout_text.splitlines()) == 2, "the payload must still be live"
    rows = split_listing_rows(stdout_text)
    assert len(rows) == 1, f"one tmux line must be one row, got {rows!r}"


@pytest.mark.parametrize("boundary", TMUX_ACCEPTED_BOUNDARIES)
def test_forged_payload_never_badges_as_owned(boundary: str) -> None:
    owned = {("cloude_work", REAL_EPOCH)}
    name = f"pwn{boundary}$99|{REAL_EPOCH}|1|cloude_work"
    stdout_text = f"$7|1787000000|1|{name}\n"

    badged: List[str] = []
    for row in split_listing_rows(stdout_text):
        parsed = parse_listing_row(row)
        if parsed is None:
            continue
        if resolve_ownership(
            parsed["name"], parsed["created_at_epoch"], owned, None,
            prefix="cloude_",
        ):
            badged.append(parsed["name"])

    assert badged == [], f"forged row badged as ours: {badged!r}"


@pytest.mark.parametrize("boundary", TMUX_ACCEPTED_BOUNDARIES)
def test_boundary_in_name_is_refused_by_the_parser(boundary: str) -> None:
    assert name_has_line_boundary(f"a{boundary}b") is True
    assert parse_listing_row(f"$3|1|1|a{boundary}b") is None


def test_multi_row_forgery_collapses_to_one_row() -> None:
    sep = " "
    name = (
        f"a{sep}$1|1|1|forged_one{sep}$2|2|1|forged_two"
        f"{sep}$3|3|1|forged_three"
    )
    stdout_text = f"$9|1787000000|1|{name}\n"

    assert len(stdout_text.splitlines()) == 4
    assert len(split_listing_rows(stdout_text)) == 1


def test_legitimate_rows_still_parse() -> None:
    stdout_text = "$1|1755000000|2|api|prod\n$2|1755000001|1|plain\n"
    rows = split_listing_rows(stdout_text)
    assert len(rows) == 2
    assert parse_listing_row(rows[0])["name"] == "api|prod"
    assert parse_listing_row(rows[1])["name"] == "plain"


def test_crlf_and_trailing_newline_do_not_create_empty_rows() -> None:
    assert split_listing_rows("$1|1|1|a\r\n$2|2|1|b\r\n") == [
        "$1|1|1|a",
        "$2|2|1|b",
    ]
    assert split_listing_rows("") == []
    assert split_listing_rows("\n\n") == []


def test_no_listing_site_uses_splitlines() -> None:
    listing_stdout_names = {"stdout_text", "raw_lines", "names"}
    offenders: List[str] = []
    trees = [ast.parse((ROOT / "src" / "core" / name).read_text())
             for name in ("tmux_backend.py", "tmux_transport/pane_listing.py")]

    for node in (n for tree in trees for n in ast.walk(tree)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "splitlines":
            continue
        receiver = func.value
        if isinstance(receiver, ast.Name) and receiver.id in listing_stdout_names:
            offenders.append(f"line {node.lineno}: {receiver.id}.splitlines()")

    assert offenders == [], (
        "tmux listing stdout must be split with split_listing_rows, not "
        "str.splitlines() - splitlines recognises NEL, LS and PS, which "
        f"tmux permits in a session name. Offenders: {offenders}"
    )


def test_backend_imports_the_row_splitter() -> None:
    source = "".join((ROOT / "src" / "core" / name).read_text()
                     for name in ("tmux_backend.py", "tmux_transport/pane_listing.py"))
    assert "split_listing_rows" in source
    assert source.count("split_listing_rows(") >= 3, (
        "all three enumeration sites (list_attachable_sessions, "
        "list_pane_status_all, discover_existing) must use it"
    )




def test_socket_path_containing_a_marker_cannot_forge_no_server() -> None:
    stderr = (
        "error connecting to /tmp/s4verify/no server running/sock "
        "(Permission denied)"
    )
    assert classify_tmux_stderr(stderr) == STDERR_CONNECT_FAILED
    listing = classify_listing_failure(1, stderr)
    assert listing.ok is False, "a probe that could not look is not an answer"
    assert listing.reason == "connect_failed"


def test_marker_in_path_with_absent_server_errno_still_reads_no_server() -> None:
    stderr = (
        "error connecting to /tmp/no server running/sock "
        "(No such file or directory)"
    )
    assert classify_tmux_stderr(stderr) == STDERR_NO_SERVER
    assert classify_listing_failure(1, stderr).ok is True


def test_newline_in_socket_path_cannot_forge_a_marker_line() -> None:
    stderr = "error connecting to /tmp/evil\nno server running (Permission denied)"
    assert classify_tmux_stderr(stderr) != STDERR_NO_SERVER
    assert classify_listing_failure(1, stderr).ok is False


def test_a_marker_mid_line_does_not_classify_as_no_server() -> None:
    for stderr in (
        "unexpected failure: no server running somewhere",
        "tmux said something about failed to connect to server earlier",
        "context: no current server, but that is not what happened here",
    ):
        assert classify_tmux_stderr(stderr) == STDERR_UNRECOGNISED, stderr
        assert classify_listing_failure(1, stderr).ok is False


def test_genuine_no_server_messages_still_classify() -> None:
    for stderr in (
        "no server running on /tmp/tmux-501/cloude",
        "no server running on /tmp/x\n",
        "  no server running on /tmp/x  ",
        "warning: something\nno server running on /tmp/x",
    ):
        assert classify_tmux_stderr(stderr) == STDERR_NO_SERVER, stderr
        assert classify_listing_failure(1, stderr).ok is True


def test_unreadable_and_empty_stderr_never_become_an_answer() -> None:
    for stderr in ("", "   ", "something entirely unexpected"):
        assert classify_tmux_stderr(stderr) == STDERR_UNRECOGNISED
        assert classify_listing_failure(1, stderr).ok is False


def test_connect_error_with_no_readable_errno_is_unrecognised() -> None:
    assert classify_tmux_stderr("error connecting to /tmp/x") == (
        STDERR_UNRECOGNISED
    )


def test_localised_errno_does_not_become_a_confident_zero() -> None:
    for stderr in (
        "error connecting to /tmp/x (Aucun fichier ou dossier de ce type)",
        "error connecting to /tmp/x (Datei oder Verzeichnis nicht gefunden)",
    ):
        assert classify_tmux_stderr(stderr) == STDERR_CONNECT_FAILED
        assert classify_listing_failure(1, stderr).ok is False




def test_listing_env_pins_lc_all_to_c() -> None:
    assert LISTING_ENV_OVERRIDES["LC_ALL"] == "C"
    env = listing_env()
    assert env["LC_ALL"] == "C"


def test_listing_env_inherits_the_rest_and_does_not_mutate_os_environ() -> None:
    marker = "S4_VERIFY_MARKER"
    os.environ[marker] = "present"
    try:
        env = listing_env()
        assert env[marker] == "present", "child must inherit the real env"
        env["LC_ALL"] = "mutated"
        assert listing_env()["LC_ALL"] == "C", "must return a fresh dict"
        assert os.environ.get("LC_ALL") != "mutated"
    finally:
        os.environ.pop(marker, None)


def test_only_the_listing_path_pins_the_locale() -> None:
    source = (ROOT / "src" / "core" / "tmux_backend.py").read_text()
    assert source.count("listing_env()") == 1, (
        "the locale pin must be applied at exactly one site, the listing "
        "path; applying it in _run_tmux_sync would leak into new-session"
    )

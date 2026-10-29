
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_listing import REASON_NO_SERVER, classify_listing_failure
from src.core.tmux_stderr import (
    REASON_CONNECT_FAILED,
    STDERR_CONNECT_FAILED,
    STDERR_NO_SERVER,
    STDERR_UNRECOGNISED,
    classify_tmux_stderr,
    looks_like_no_server,
)
from src.core.tmux_listing_parse import (
    FIELD_SEPARATOR,
    LISTING_FORMAT,
    parse_listing_row,
    resolve_ownership,
)


MEASURED_CONNECT_FAILURES = (
    "error connecting to /tmp/x/sock (Permission denied)",
    "error connecting to /tmp/x/sock (Socket operation on non-socket)",
    "error connecting to /very/long/path/sock (File name too long)",
)

MEASURED_NO_SERVER = (
    "error connecting to /tmp/x/absent (No such file or directory)",
    "no server running on /tmp/x/sock",
    "failed to connect to server",
    "no current server",
)


@pytest.mark.parametrize("stderr_text", MEASURED_CONNECT_FAILURES)
def test_a_connect_error_that_is_not_ENOENT_is_NOT_an_answer(stderr_text):
    assert classify_tmux_stderr(stderr_text) == STDERR_CONNECT_FAILED
    assert looks_like_no_server(stderr_text) is False
    listing = classify_listing_failure(1, stderr_text)
    assert listing.ok is False
    assert listing.sessions == []
    assert listing.reason == REASON_CONNECT_FAILED
    assert listing.detail == stderr_text


@pytest.mark.parametrize("stderr_text", MEASURED_NO_SERVER)
def test_a_genuine_absent_server_still_IS_a_complete_answer_of_zero(stderr_text):
    assert classify_tmux_stderr(stderr_text) == STDERR_NO_SERVER
    assert looks_like_no_server(stderr_text) is True
    listing = classify_listing_failure(1, stderr_text)
    assert listing.ok is True
    assert listing.sessions == []
    assert listing.reason == REASON_NO_SERVER


@pytest.mark.parametrize(
    "stderr_text",
    [
        "",
        "   ",
        "lost server",
        "error connecting to /tmp/x/sock",
        "no such file or directory",
    ],
)
def test_an_UNRECOGNISED_stderr_defaults_to_could_not_evaluate(stderr_text):
    assert classify_tmux_stderr(stderr_text) == STDERR_UNRECOGNISED
    assert looks_like_no_server(stderr_text) is False
    assert classify_listing_failure(1, stderr_text).ok is False


@pytest.mark.parametrize(
    "stderr_text",
    [
        "error connecting to /tmp/x (Some Errno From tmux 4.0)",
        "error connecting to /tmp/x ()",
        "error connecting to /tmp/x (Connection refused)",
    ],
)
def test_an_errno_OUTSIDE_the_allowlist_is_a_connect_failure(stderr_text):
    assert classify_tmux_stderr(stderr_text) == STDERR_CONNECT_FAILED
    assert looks_like_no_server(stderr_text) is False
    assert classify_listing_failure(1, stderr_text).ok is False


def test_a_socket_path_containing_parentheses_does_not_confuse_the_errno():
    text = "error connecting to /tmp/my (weird) dir/sock (Permission denied)"
    assert classify_tmux_stderr(text) == STDERR_CONNECT_FAILED
    ok_text = "error connecting to /tmp/my (weird) dir/s (No such file or directory)"
    assert classify_tmux_stderr(ok_text) == STDERR_NO_SERVER


def test_the_no_server_ALLOWLIST_is_exactly_one_errno():
    from src.core.tmux_stderr import _NO_SERVER_CONNECT_ERRNOS

    assert _NO_SERVER_CONNECT_ERRNOS == frozenset({"no such file or directory"})


def test_looks_like_no_server_is_TRUE_for_exactly_one_of_three_outcomes():
    for verdict, sample in (
        (STDERR_NO_SERVER, "no server running on /x"),
        (STDERR_CONNECT_FAILED, "error connecting to /x (Permission denied)"),
        (STDERR_UNRECOGNISED, "lost server"),
    ):
        assert classify_tmux_stderr(sample) == verdict
        assert looks_like_no_server(sample) is (verdict == STDERR_NO_SERVER)




def test_the_forged_line_from_the_demonstration_is_REFUSED():
    assert parse_listing_row("victim|1755000000|1|1787070480|1") is None


def test_a_pipe_in_a_session_name_survives_VERBATIM():
    row = parse_listing_row("$3|1755000000|2|api|prod")
    assert row == {
        "session_id": "$3",
        "created_at_epoch": 1755000000,
        "window_count": 2,
        "name": "api|prod",
    }


@pytest.mark.parametrize(
    "hostile_name",
    [
        "a|b",
        "a|b|c|d|e",
        "|leading",
        "trailing|",
        "$9|1|1",
        "  spaced  |  name  ",
        "unicode |namé| 中文",
    ],
)
def test_no_session_name_can_alter_the_fields_in_front_of_it(hostile_name):
    line = f"$7|1787070480|4|{hostile_name}"
    row = parse_listing_row(line)
    assert row is not None
    assert row["session_id"] == "$7"
    assert row["created_at_epoch"] == 1787070480
    assert row["window_count"] == 4
    assert row["name"] == hostile_name


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "garbage",
        "$3|1755000000|2",
        "3|1755000000|2|name",
        "$x|1755000000|2|name",
        "$3|notanepoch|2|name",
        "$3|1755000000|notanint|name",
        "$3|1755000000|2|",
        "$3|-1|2|name",
    ],
)
def test_a_row_that_does_not_VALIDATE_is_refused_not_guessed(line):
    assert parse_listing_row(line) is None


def test_the_FORMAT_STRING_puts_the_caller_controlled_field_LAST():
    fields = LISTING_FORMAT.split(FIELD_SEPARATOR)
    assert fields[-1] == "#{session_name}", (
        "the caller-controlled session NAME must be the LAST field, or a "
        "name containing the delimiter can forge the fields after it"
    )
    assert "#{session_name}" not in fields[:-1]
    assert fields[:-1] == [
        "#{session_id}",
        "#{session_created}",
        "#{session_windows}",
    ]


def test_the_split_is_BOUNDED_to_the_leading_field_count():
    from src.core.tmux_listing_parse import _MAXSPLIT

    assert _MAXSPLIT == len(LISTING_FORMAT.split(FIELD_SEPARATOR)) - 1


def test_the_app_cannot_MINT_a_name_containing_the_delimiter():
    from src.core.session_name_claim import sanitize_tmux_name as _sanitize_tmux_name

    assert FIELD_SEPARATOR not in _sanitize_tmux_name("api|prod")
    assert _sanitize_tmux_name("api|prod") == "api_prod"
    assert _sanitize_tmux_name("a\nb") == "a b"
    assert _sanitize_tmux_name("a\tb") == "a b"
    assert _sanitize_tmux_name("a\x00b") == "a_b"




def test_a_None_epoch_matches_NOTHING():
    assert resolve_ownership("foo", 1, {("foo", None)}, None) is False
    assert resolve_ownership("foo", 9999, {("foo", None)}, None) is False


def test_a_stored_epoch_for_the_NAME_is_a_negative_answer_for_other_epochs():
    owned = {("cloude_work", 1755000000)}
    legacy = {"cloude_work"}
    assert resolve_ownership("cloude_work", 1787070999, owned, legacy) is False
    assert resolve_ownership("cloude_work", 1755000000, owned, legacy) is True


def test_the_legacy_tier_survives_when_the_DB_is_silent_about_the_name():
    assert resolve_ownership("fresh", 5, {("other", 1)}, {"fresh"}) is True


def test_an_empty_instance_set_is_an_ANSWER_not_a_fallback():
    assert resolve_ownership("cloude_x", 1, set(), None) is False
    assert resolve_ownership("cloude_x", 1, None, None, prefix="cloude_") is True


def test_the_prefix_heuristic_applies_ONLY_when_neither_source_was_supplied():
    assert resolve_ownership("cloude_x", 1, None, set(), prefix="cloude_") is False
    assert resolve_ownership("cloude_x", 1, set(), None, prefix="cloude_") is False
    assert resolve_ownership("cloude_x", 1, None, None, prefix="cloude_") is True


def test_the_prefix_heuristic_recognises_both_carnivore_rename_prefixes():
    assert resolve_ownership("cloude_x", 1, None, None, prefix="cloude_") is True
    assert resolve_ownership("carnivore_x", 1, None, None, prefix="cloude_") is True
    assert resolve_ownership("somebody_elses", 1, None, None, prefix="cloude_") is False
    assert resolve_ownership("cloude_x", 1, None, None) is False
    assert resolve_ownership("carnivore_x", 1, None, None) is False

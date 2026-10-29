
from __future__ import annotations

import sys

import pytest

from tests.lifecycle_helpers import ROOT, add_row, conn, row_by_uuid

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402,F401

from src.core.session_label import (
    LABEL_MAX_CHARS,
    InvalidLabel,
    label_from_tmux_name,
    set_label,
    validate_label,
)




@pytest.mark.parametrize(
    "label",
    [
        "Media Compression",
        "the one with the weird ffmpeg bug",
        "client: acme (v2)",
        "cost/benefit 50%",
        "emoji is fine here",
        "a" * LABEL_MAX_CHARS,
    ],
)
def test_a_label_may_contain_anything_printable(label):
    assert validate_label(label) == label


@pytest.mark.parametrize(
    "label",
    ["", "   ", "line\nbreak", "tab\there", "nul\x00byte", "a" * (LABEL_MAX_CHARS + 1)],
)
def test_a_label_is_still_refused_when_it_cannot_be_rendered(label):
    with pytest.raises(InvalidLabel):
        validate_label(label)


def test_a_label_is_stripped_of_surrounding_whitespace():
    assert validate_label("  spaced out  ") == "spaced out"






def test_setting_a_label_writes_title_and_touches_no_identity_column(conn):
    add_row(conn, uuid="u-lab", name="cloude_Media", epoch=1787686975,
            tmux_session_id="$0")

    assert set_label(conn, session_uuid="u-lab", label="Media Compression")

    row = row_by_uuid(conn, "u-lab")
    assert row["title"] == "Media Compression"
    assert row["tmux_name"] == "cloude_Media", (
        "renaming a LABEL must not touch the tmux name - that is the "
        "field whose movement split one session into two rows"
    )
    assert row["tmux_created_epoch"] == 1787686975
    assert row["tmux_session_id"] == "$0"
    assert row["session_uuid"] == "u-lab"


def test_a_label_can_be_changed_repeatedly(conn):
    add_row(conn, uuid="u-twice", name="n", epoch=1, tmux_session_id="$1")
    set_label(conn, session_uuid="u-twice", label="first")
    set_label(conn, session_uuid="u-twice", label="second")
    assert row_by_uuid(conn, "u-twice")["title"] == "second"


def test_setting_a_label_on_a_row_that_is_not_there_reports_false(conn):
    assert set_label(conn, session_uuid="nope", label="x") is False


def test_an_invalid_label_never_reaches_the_table(conn):
    add_row(conn, uuid="u-bad", name="n", epoch=1)
    with pytest.raises(InvalidLabel):
        set_label(conn, session_uuid="u-bad", label="bad\nlabel")
    assert row_by_uuid(conn, "u-bad")["title"] is None




@pytest.mark.parametrize(
    "tmux_name,expected",
    [
        ("cloude_Media", "Media"),
        ("Media_Compression", "Media Compression"),
        ("cloude_my_long_thing", "my long thing"),
        ("cloude_", "cloude"),
        ("plain", "plain"),
    ],
)
def test_a_label_derived_from_a_tmux_name_drops_the_app_prefix(
    tmux_name, expected
):
    assert label_from_tmux_name(tmux_name) == expected

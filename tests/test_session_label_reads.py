
from __future__ import annotations

import sys

from tests.lifecycle_helpers import ROOT, SOCKET, add_row, conn  # noqa: F401

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402

from src.core.session_label import label_for_instance, label_for_name


def _title(conn, uuid, title):
    conn.execute(
        "UPDATE sessions SET title = ? WHERE session_uuid = ?", (title, uuid)
    )


def test_an_exact_instance_read_answers_that_instances_label(conn):
    add_row(conn, uuid="u1", name="cloude_a", epoch=1000)
    _title(conn, "u1", "Image Tool")
    assert (
        label_for_instance(conn, socket=SOCKET, name="cloude_a", epoch=1000)
        == "Image Tool"
    )


def test_an_exact_instance_read_refuses_a_different_epoch(conn):
    add_row(conn, uuid="u1", name="cloude_a", epoch=1000)
    _title(conn, "u1", "Image Tool")
    assert (
        label_for_instance(conn, socket=SOCKET, name="cloude_a", epoch=2000)
        is None
    )


def test_an_exact_instance_read_with_no_epoch_answers_none(conn):
    add_row(conn, uuid="u1", name="cloude_a", epoch=1000)
    _title(conn, "u1", "Image Tool")
    assert (
        label_for_instance(conn, socket=SOCKET, name="cloude_a", epoch=None)
        is None
    )


def test_the_name_read_answers_the_newest_rows_label(conn):
    add_row(conn, uuid="u1", name="cloude_a", epoch=1000)
    _title(conn, "u1", "the old one")
    add_row(conn, uuid="u2", name="cloude_a", epoch=2000)
    _title(conn, "u2", "the live one")
    assert label_for_name(conn, socket=SOCKET, name="cloude_a") == "the live one"


def test_a_dead_predecessor_never_lends_its_label_to_an_unnamed_successor(conn):
    add_row(conn, uuid="u1", name="cloude_a", epoch=1000)
    _title(conn, "u1", "the old one")
    add_row(conn, uuid="u2", name="cloude_a", epoch=2000)
    assert label_for_name(conn, socket=SOCKET, name="cloude_a") is None


def test_an_empty_title_counts_as_no_label(conn):
    add_row(conn, uuid="u1", name="cloude_a", epoch=1000)
    _title(conn, "u1", "   ")
    assert label_for_name(conn, socket=SOCKET, name="cloude_a") is None
    assert (
        label_for_instance(conn, socket=SOCKET, name="cloude_a", epoch=1000)
        is None
    )


def test_an_unknown_name_answers_none_rather_than_raising(conn):
    assert label_for_name(conn, socket=SOCKET, name="cloude_nope") is None
    assert (
        label_for_instance(conn, socket=SOCKET, name="cloude_nope", epoch=1)
        is None
    )


def test_a_label_carrying_punctuation_reads_back_verbatim(conn):
    hairy = 'client: acme v2.1 "prod" $rate'
    add_row(conn, uuid="u1", name="cloude_client_acme", epoch=1000)
    _title(conn, "u1", hairy)
    assert (
        label_for_instance(
            conn, socket=SOCKET, name="cloude_client_acme", epoch=1000
        )
        == hairy
    )
    assert label_for_name(conn, socket=SOCKET, name="cloude_client_acme") == hairy

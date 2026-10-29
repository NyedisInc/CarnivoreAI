
from __future__ import annotations

import os
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_models import (  # noqa: E402
    SESSION_ORIGIN_ADOPTED,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.session_adopt_persist import persist_adoption  # noqa: E402
from src.core.session_identity import (  # noqa: E402
    ADOPT_CLAIMED,
    claim_instance,
    record_instance,
)
from src.core.session_store import (  # noqa: E402
    is_owned_origin,
    owned_instances,
)
from tests.s7_helpers import (  # noqa: E402
    TEST_SOCKET,
    listing_of,
    listing_row,
    migrated_connection,
    session_row,
)

EPOCH = 1786913176
NAME = "cloudes7_ext"


@pytest.fixture()
def state_dir(tmp_path):
    with closing(migrated_connection(tmp_path)):
        pass
    return tmp_path


@pytest.fixture()
def conn(state_dir):
    with closing(connect(db_path_for(state_dir))) as connection:
        yield connection




def test_adoption_survives_reopening_the_database_from_disk(state_dir):
    with closing(connect(db_path_for(state_dir))) as first:
        result = persist_adoption(
            first,
            socket=TEST_SOCKET,
            name=NAME,
            listing=listing_of([listing_row(NAME, EPOCH)]),
        )
        assert result.persisted, result.detail
        first.commit()

    with closing(connect(db_path_for(state_dir))) as second:
        stored = session_row(second, NAME)
        assert stored["origin"] == SESSION_ORIGIN_ADOPTED
        assert is_owned_origin(stored["origin"]) is True
        assert (NAME, EPOCH) in owned_instances(second, socket=TEST_SOCKET)


def test_the_row_is_observed_before_adoption_and_adopted_after(conn):
    record_instance(
        conn,
        socket=TEST_SOCKET,
        name=NAME,
        epoch=EPOCH,
        origin=SESSION_ORIGIN_OBSERVED,
    )
    assert session_row(conn, NAME)["origin"] == SESSION_ORIGIN_OBSERVED
    assert owned_instances(conn, socket=TEST_SOCKET) == set()

    assert claim_instance(
        conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH
    ).claimed
    assert session_row(conn, NAME)["origin"] == SESSION_ORIGIN_ADOPTED
    assert (NAME, EPOCH) in owned_instances(conn, socket=TEST_SOCKET)


def test_a_later_observed_sighting_does_not_demote_an_adopted_session(conn):
    persist_adoption(
        conn,
        socket=TEST_SOCKET,
        name=NAME,
        listing=listing_of([listing_row(NAME, EPOCH)]),
    )
    record_instance(
        conn,
        socket=TEST_SOCKET,
        name=NAME,
        epoch=EPOCH,
        origin=SESSION_ORIGIN_OBSERVED,
    )
    assert session_row(conn, NAME)["origin"] == SESSION_ORIGIN_ADOPTED




def test_ownership_rebuilds_from_disk_with_no_in_memory_manager(state_dir):
    with closing(connect(db_path_for(state_dir))) as writer:
        persist_adoption(
            writer,
            socket=TEST_SOCKET,
            name=NAME,
            listing=listing_of([listing_row(NAME, EPOCH)]),
        )
        writer.commit()

    from src.core.tmux_listing_parse import resolve_ownership

    with closing(connect(db_path_for(state_dir))) as reader:
        instances = owned_instances(reader, socket=TEST_SOCKET)

    assert resolve_ownership(
        NAME, EPOCH, instances, set(), prefix="cloude_"
    ) is True


def test_a_different_instance_of_the_same_name_is_not_adopted(state_dir):
    with closing(connect(db_path_for(state_dir))) as writer:
        persist_adoption(
            writer,
            socket=TEST_SOCKET,
            name=NAME,
            listing=listing_of([listing_row(NAME, EPOCH)]),
        )
        writer.commit()

    from src.core.tmux_listing_parse import resolve_ownership

    with closing(connect(db_path_for(state_dir))) as reader:
        instances = owned_instances(reader, socket=TEST_SOCKET)

    assert resolve_ownership(
        NAME, EPOCH + 1, instances, set(), prefix="cloude_"
    ) is False




def test_adopted_at_keeps_its_first_value_across_repeat_adoptions(conn):
    first_stamp = "2026-01-01T00:00:00Z"
    second_stamp = "2026-06-01T00:00:00Z"
    record_instance(
        conn,
        socket=TEST_SOCKET,
        name=NAME,
        epoch=EPOCH,
        origin=SESSION_ORIGIN_OBSERVED,
    )

    assert claim_instance(
        conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, now=first_stamp
    ).claimed
    assert claim_instance(
        conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, now=second_stamp
    ).claimed

    stored = session_row(conn, NAME)
    assert stored["adopted_at"] == first_stamp, (
        "adopted_at moved on re-adoption. The UI re-enters this path on "
        "every session re-open, so a moving stamp rewrites history "
        "constantly"
    )
    assert stored["updated_at"] == second_stamp
    assert stored["origin"] == SESSION_ORIGIN_ADOPTED


def test_repeat_adoption_through_the_full_path_also_holds_the_stamp(conn):
    listing = listing_of([listing_row(NAME, EPOCH)])
    first = persist_adoption(
        conn, socket=TEST_SOCKET, name=NAME, listing=listing,
        now="2026-02-02T00:00:00Z",
    )
    assert first.persisted
    stamp = session_row(conn, NAME)["adopted_at"]
    uuid_before = session_row(conn, NAME)["session_uuid"]

    second = persist_adoption(
        conn, socket=TEST_SOCKET, name=NAME, listing=listing,
        now="2026-09-09T00:00:00Z",
    )
    assert second.persisted
    after = session_row(conn, NAME)
    assert after["adopted_at"] == stamp
    assert after["session_uuid"] == uuid_before, (
        "re-adoption minted a new external identity, so every reference "
        "to the old one is now dangling"
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE tmux_name = ?", (NAME,)
    ).fetchone()[0] == 1


def test_adopt_result_claimed_is_true_only_for_the_claimed_outcome():
    from src.core.session_identity import ADOPT_FAILURES, AdoptResult

    assert AdoptResult(outcome=ADOPT_CLAIMED).claimed is True
    for outcome in ADOPT_FAILURES:
        assert AdoptResult(outcome=outcome).claimed is False
    assert len(set(ADOPT_FAILURES)) == 3

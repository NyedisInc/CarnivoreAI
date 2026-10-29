from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from src.core.db import connect, db_path_for
from src.core.db_models import SESSION_ATTRIBUTION_UNKNOWN, SESSION_ORIGIN_OBSERVED
from src.core.session_attribution import backfill_attribution, live_instance_keys
from src.core.session_identity import record_instance
from tests.s7_helpers import TEST_SOCKET, insert_project, listing_of, listing_row, migrated_connection, session_row


@pytest.fixture()
def conn(tmp_path: Path):
    with closing(migrated_connection(tmp_path)):
        pass
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection


def _seed(conn, name: str, epoch: int) -> None:
    record_instance(conn, socket=TEST_SOCKET, name=name, epoch=epoch, origin=SESSION_ORIGIN_OBSERVED,
                    project_attribution=SESSION_ATTRIBUTION_UNKNOWN)


def test_a_namesake_with_another_epoch_is_not_probed(conn) -> None:
    home = str(Path.home())
    insert_project(conn, f"{home}/Development/Proj", "P")
    _seed(conn, "reused_name", 100)
    probed: list = []

    def probe(name: str):
        probed.append(name)
        return f"{home}/Development/Proj/src"

    live = live_instance_keys(TEST_SOCKET, listing_of([listing_row("reused_name", 200, working_dir=None)]))
    result = backfill_attribution(conn, working_dir_probe=probe, live_instances=live)
    assert probed == []
    assert result.still_unknown == 1
    assert session_row(conn, "reused_name")["working_dir"] is None


def test_a_matching_live_instance_is_still_probed(conn) -> None:
    home = str(Path.home())
    insert_project(conn, f"{home}/Development/Proj", "P")
    _seed(conn, "live_name", 300)
    live = live_instance_keys(TEST_SOCKET, listing_of([listing_row("live_name", 300, working_dir=None)]))
    result = backfill_attribution(conn, working_dir_probe=lambda n: f"{home}/Development/Proj/src",
                                  live_instances=live)
    assert result.attributed_project == 1

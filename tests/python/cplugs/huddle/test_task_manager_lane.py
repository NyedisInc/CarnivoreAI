
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from src.core.work.ladder import data_rungs
from src.cplugs.huddle import lane
from src.core.work.ladder import MIGRATIONS
from src.core.work.storage import LEGACY_STORAGE
from tests.python.cplugs.huddle.test_task_manager_state_rungs import ITEM_INSERT, real_copy, walk

PROVENANCE: List[Tuple[str, str, str, str, str]] = [
    ("12", "owner", "", "", "task_manager"),
    ("12", "uuid-session-1", "", "", "task_manager"),
    ("12", "", "", "", "task_manager"),
    ("all", "owner", "", "owner", "task_manager"),
    ("12", "owner", "", "owner_message", "task_manager"),
    ("12", "uuid-session-1", "", "session:uuid-session-1", "task_manager"),
    ("12", "agent:7", "", "agent:7", "swarm"),
    ("12", "agent:7", "", "spawn:9", "swarm"),
    ("12", "swarm", "", "", "swarm"),
    ("12", "owner", "trust:4:ab", "", "swarm"),
    ("agent:3", "owner", "chat", "", "swarm"),
    ("agent:3", "uuid-session-1", "", "", "swarm"),
]


def synthetic_v37(folder: Path) -> Path:
    path = folder / "huddle.db"
    with closing(sqlite3.connect(path)) as conn, conn:
        for step in MIGRATIONS[:37]:
            conn.executescript(step)
        for n, (list_key, created_key, swarm_ref, origin, _) in enumerate(PROVENANCE):
            conn.execute(ITEM_INSERT, (f"row {n}", "", n, "open"))
            conn.execute("UPDATE items SET list_key = ?, created_key = ?, swarm_ref = ?, card_origin = ? WHERE id = last_insert_rowid()",
                         (list_key, created_key, swarm_ref, origin))
        conn.execute("PRAGMA user_version = 37")
    return path


def rows_without_lane(path: Path) -> List[tuple]:
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        return [tuple(r[k] for k in r.keys() if k != "lane") for r in conn.execute("SELECT * FROM items ORDER BY id")]


def lanes(path: Path) -> List[str]:
    with closing(sqlite3.connect(path)) as conn:
        return [r[0] for r in conn.execute("SELECT lane FROM items ORDER BY id")]


def test_the_rung_backfills_every_provenance_as_the_rule_says_and_changes_nothing_else(tmp_path: Path):
    path = synthetic_v37(tmp_path)
    before = rows_without_lane_before(path)
    walk(path, 38)
    assert lanes(path) == [expected for *_, expected in PROVENANCE]
    assert rows_without_lane(path) == before


def rows_without_lane_before(path: Path) -> List[tuple]:
    with closing(sqlite3.connect(path)) as conn:
        return [tuple(r) for r in conn.execute("SELECT * FROM items ORDER BY id")]


def test_the_sql_rule_and_the_python_rule_agree_on_every_provenance(tmp_path: Path):
    path = synthetic_v37(tmp_path)
    walk(path, 38)
    for list_key, created_key, swarm_ref, origin, expected in PROVENANCE:
        assert lane.for_new(list_key=list_key, created_key=created_key, swarm_ref=swarm_ref, card_origin=origin) == expected, (list_key, created_key, swarm_ref, origin)


def test_owners_real_file_loses_no_row_and_every_task_stays_in_his_lane(tmp_path: Path):
    path = real_copy(tmp_path, at_most=37)
    walk(path, 37)
    before = rows_without_lane_before(path)
    walk(path, 38)
    assert rows_without_lane(path) == before
    with closing(sqlite3.connect(path)) as conn:
        swarm = conn.execute("SELECT COUNT(*) FROM items WHERE lane = 'swarm'").fetchone()[0]
        swarm_shaped = conn.execute("SELECT COUNT(*) FROM items WHERE swarm_ref != '' OR created_key = 'swarm' OR list_key LIKE 'agent:%' "
                                    "OR card_origin LIKE 'agent:%' OR card_origin LIKE 'spawn:%'").fetchone()[0]
    assert swarm == swarm_shaped


def test_the_ladder_takes_a_backup_before_the_lane_rung_for_a_file_already_past_the_renames(tmp_path: Path):
    path = synthetic_v37(tmp_path)
    from src.cplugs.sdk import CplugStorage
    CplugStorage(path.parent, LEGACY_STORAGE).connect(True).close()
    copies = [p.name for p in path.parent.iterdir() if p.name.startswith("huddle.db.pre-lane-")]
    assert len(copies) == 1 and LEGACY_STORAGE.backup_before[38] == "pre-lane" == data_rungs.BACKUPS[38]


def test_a_new_item_gets_its_lane_at_insert():
    assert lane.for_new(list_key="12", created_key="owner") == lane.TASK_MANAGER
    assert lane.for_new(list_key="agent:7") == lane.SWARM
    assert lane.for_new(list_key="12", swarm_ref="chat") == lane.SWARM
    assert lane.for_new(list_key="12", card_origin="spawn:2") == lane.SWARM
    assert lane.from_origin("") == lane.TASK_MANAGER

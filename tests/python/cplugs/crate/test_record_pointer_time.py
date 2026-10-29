
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from src.cplugs.crate import record
from src.cplugs.crate.writer import mint_bundle_id
from src.cplugs.sdk import exports as sx
from tests.python.cplugs.crate.crate_world import env_for, make_world

DAY = 86_400
CONV = "c58d095c-7e14-49a6-8dfb-23792a5d3f54"


def _rec(bundle_id: str, created: int, path: Path) -> dict:
    return record.published_record(bundle_id=bundle_id, path=str(path), sha256=hashlib.sha256(bundle_id.encode()).hexdigest(),
                                   size=1, scope="session", variant="own", created_epoch=created, label=None,
                                   project_uid=None, session_uuid=None,
                                   conversations=[{"id": CONV, "family": "claude", "title": "t"}])


def test_an_older_crate_recorded_later_keeps_the_newer_pointer(tmp_path: Path) -> None:
    env = env_for(make_world(tmp_path))
    day1 = int(time.time()) - 30 * DAY
    older, newer = mint_bundle_id("own", "session", day1), mint_bundle_id("own", "session", day1 + 9 * DAY)
    record.record_published(env, _rec(newer, day1 + 9 * DAY, tmp_path / "b.crate"), time.time())
    record.record_published(env, _rec(older, day1, tmp_path / "a.crate"), time.time() + 5)
    pointer = sx.with_main_db(lambda conn: sx.pointers_for(conn, [CONV]), state=env.state)[CONV]
    assert pointer.bundle_id == newer and pointer.exported_at == float(day1 + 9 * DAY)

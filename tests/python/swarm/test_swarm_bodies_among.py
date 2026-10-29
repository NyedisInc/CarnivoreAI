
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import facade as facade_module
from src.core.swarm import store
from src.core.swarm.facade import SwarmFacade


def _row(session_id: str, row_id: int) -> SimpleNamespace:
    return SimpleNamespace(session=SimpleNamespace(id=session_id), session_row_id=row_id)


def test_bodies_among_one_read_and_no_full_listing(tmp_path, monkeypatch):
    assert ensure_db_migrated(tmp_path).status == "ok"
    with connect(db_path_for(tmp_path)) as conn:
        for n in range(3):
            conn.execute("INSERT INTO sessions (id, session_uuid, origin, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (100 + n, f"uuid-{n}", "created", 1.0, 1.0))
        agent = store.create_agent(conn, slug="loki", rank="alpha", job="j", display_name="Loki", repo_dir=str(tmp_path), effort="low")
        conn.execute("UPDATE swarm_agents SET session_row_id = 100 WHERE id = ?", (agent["id"],))
        conn.commit()

    async def no_listing():
        raise AssertionError("bodies_among must not take a full listing")

    reads = []
    real_read = SwarmFacade._read
    monkeypatch.setattr(SwarmFacade, "_read", lambda self, work, default: reads.append(1) or real_read(self, work, default))
    facade = SwarmFacade(tmp_path, no_listing)
    rows = [_row("ses_body", 100), _row("ses_b", 101), _row("ses_c", 102), SimpleNamespace(session=SimpleNamespace(id="ses_d"))]
    assert asyncio.run(facade.bodies_among(rows)) == frozenset({"ses_body"})
    assert len(reads) == 1
    assert facade_module.SwarmFacade.bodies_among is not None

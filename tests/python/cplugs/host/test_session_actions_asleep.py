
from types import SimpleNamespace

import pytest

from src.api import asleep_brief
from src.api import recreate_routes as rr
from src.cplugs.host import session_actions


@pytest.mark.asyncio
async def test_asleep_names_a_record_by_title_then_tmux_name(monkeypatch, tmp_path):
    db = tmp_path / "carnivore.db"
    db.write_bytes(b"")
    rows = [{"session_uuid": "u1", "project_id": 7, "title": "Fix nudges", "tmux_name": "carnivore_a"},
            {"session_uuid": "u2", "project_id": 7, "title": None, "tmux_name": "carnivore_b"}]
    monkeypatch.setattr(rr, "_db_path", lambda: db)
    monkeypatch.setattr(asleep_brief, "read_asleep_rows", lambda path: rows if path == db else [])
    out = await session_actions.asleep(SimpleNamespace(app=SimpleNamespace(state=None)))
    assert out == [{"session_uuid": "u1", "project_id": 7, "name": "Fix nudges"},
                   {"session_uuid": "u2", "project_id": 7, "name": "carnivore_b"}]

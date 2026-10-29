from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.api.session_companion_routes import companion_infos, list_companions
from src.api.session_listing_collections import listing_collections
from src.core.sessions.registry import SessionRegistry


def _state():
    reg = SessionRegistry(log_cap=10)
    reg.sessions = {"ses_agent": SimpleNamespace(id="ses_agent"), "ses_shell": SimpleNamespace(id="ses_shell")}
    reg.hide_when(lambda s: s.id == "ses_shell")
    built = []

    def info(sid, **_kw):
        built.append(sid)
        return SimpleNamespace(session_id=sid)

    manager = SimpleNamespace(
        _registry=reg, _status_map_for_listing=lambda: {}, _owned=SimpleNamespace(instances_from_db=lambda: None),
        _session_info_for=info)
    return SimpleNamespace(session_manager=manager), reg, built


@pytest.mark.asyncio
async def test_rows_carry_no_companion_the_collection_does_and_a_peer_gets_neither():
    state, reg, built = _state()
    assert reg.listable_ids() == ["ses_agent"]
    assert [i.session_id for i in await companion_infos(state)] == ["ses_shell"]
    assert built == ["ses_shell"]
    assert "companions" in [c.name for c in listing_collections(state)]
    peer = SimpleNamespace(app=SimpleNamespace(state=state), state=SimpleNamespace(peer_grant=object()))
    assert await list_companions(peer) == []

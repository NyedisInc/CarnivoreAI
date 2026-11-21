
from __future__ import annotations

import asyncio
from typing import Any, List

import pytest
from fastapi import HTTPException

from src.api import pack_relay_routes
from src.core import resource_push
from src.core.resource_push import topics


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    announced: List[str] = []
    monkeypatch.setattr(pack_relay_routes, "_account_providers", lambda: {"larkspur": "claude"})
    monkeypatch.setattr(pack_relay_routes, "_write", lambda *a, **k: ["iid-gone"])
    monkeypatch.setattr(pack_relay_routes, "_read", lambda: {"accounts": {}, "default_on": []})
    monkeypatch.setattr(pack_relay_routes.relay_runtime, "RELAY", None)
    monkeypatch.setattr(pack_relay_routes.ledger_sync_store, "forget", lambda *a, **k: None)
    monkeypatch.setattr(resource_push, "notify", lambda topic, *a, **k: announced.append(topic))
    return announced


def _put(account: str, machines: List[str]) -> Any:
    body = pack_relay_routes.RelayBody(machines=machines)
    return asyncio.run(pack_relay_routes.put_relay(account, body, None))  # type: ignore[arg-type]


def test_put_relay_off_announces_pack_relay(seams: List[str]) -> None:
    _put("larkspur", [])
    assert seams == [topics.PACK_RELAY]


def test_put_relay_unknown_account_announces_nothing(seams: List[str]) -> None:
    with pytest.raises(HTTPException):
        _put("nope", [])
    assert seams == []


def test_put_tracks_master_announces_its_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api import pack_machines_routes as routes

    announced: List[str] = []

    class _State:
        def save_tracks_master(self, value: bool) -> bool:
            return True

    class _Wired:
        state = _State()

        def sync_scopes(self) -> None:
            return None

    monkeypatch.setattr(routes, "_wired", lambda: _Wired())
    monkeypatch.setattr(resource_push, "notify", lambda topic, *a, **k: announced.append(topic))
    out = asyncio.run(routes.put_tracks_master(routes.TracksMasterBody(tracks_master=False), None))  # type: ignore[arg-type]
    assert out == {"tracks_master": False}
    assert announced == [topics.PACK_TRACKS_MASTER]

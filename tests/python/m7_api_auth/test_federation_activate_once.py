
from __future__ import annotations

import asyncio
from typing import Any, List

import pytest

from src.api import federation_pending_routes as routes
from src.core.federation import pair_sas


@pytest.fixture(autouse=True)
def _fresh_pending(monkeypatch: pytest.MonkeyPatch) -> pair_sas.PendingPairs:
    pending = pair_sas.PendingPairs()
    monkeypatch.setattr(pair_sas, "ACCEPTING", pending)
    monkeypatch.setattr(routes, "refuse_tls_pairing", lambda install_id: None)
    return pending


def _pairing(pending: pair_sas.PendingPairs) -> pair_sas.Pending:
    return pending.add("n1", proof="typed", sas="12345 67890", label="peer", fid="f", accepted=True, owner_ok=True,
                       install_id="inst", public_key="pk", remote_grant_id="r", grant_id="g")


def test_two_requests_on_one_ready_pairing_run_the_grant_once(monkeypatch, _fresh_pending) -> None:
    runs: List[Any] = []

    async def fake_db(fn: Any) -> None:
        runs.append(fn)
        await asyncio.sleep(0)
        return None

    monkeypatch.setattr(routes, "_db", fake_db)
    p = _pairing(_fresh_pending)

    async def both() -> None:
        await asyncio.gather(routes._activate(p), routes._activate(p))

    asyncio.run(both())
    assert len(runs) == 1
    assert _fresh_pending.get("n1") is None


def test_a_failed_activation_keeps_the_pairing_waiting(monkeypatch, _fresh_pending) -> None:
    async def failing_db(fn: Any) -> None:
        raise routes.GrantError("grant_failed", "boom")

    monkeypatch.setattr(routes, "_db", failing_db)
    p = _pairing(_fresh_pending)
    with pytest.raises(Exception):
        asyncio.run(routes._activate(p))
    assert _fresh_pending.get("n1") is not None, "a failed activation must leave the pairing to retry or expire"

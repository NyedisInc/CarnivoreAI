
from __future__ import annotations

import asyncio
import time

from src.core.byoai import transport
from src.core.byoai.contracts import Connection
from src.core.skill_manager import card_art

CONNECTION = Connection(id="c1", preset="custom", base_url="http://127.0.0.1:9/v1")


class HungClient:

    def __init__(self, *_, **__):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def request(self, *_, **__):
        await asyncio.sleep(3600)


def test_hung_provider_call_times_out_and_the_card_art_slot_is_freed(monkeypatch, tmp_path):
    monkeypatch.setattr(transport.httpx, "AsyncClient", HungClient)
    monkeypatch.setattr(card_art, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(card_art, "enabled", lambda: True)
    monkeypatch.setattr(card_art, "build_prompt", lambda name, description: "p")

    async def hung_make(_prompt):
        await transport.raw(CONNECTION, None, "POST", "/images", json={}, timeout=0.3)

    monkeypatch.setattr(card_art, "_make", hung_make)
    key = "a" * 32
    card_art._inflight.add(key)
    started = time.monotonic()
    result = card_art._job(key, "skill", "does a thing", False)
    assert time.monotonic() - started < 5
    assert result == {"status": "failed", "reason": "ProviderTimeout"}
    assert key not in card_art._inflight
    note = card_art._read_fail(key)
    assert note["attempts"] == 1 and card_art._fail_path(key).exists()


from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

from src.cplugs.flow import service, store
from src.core.flow_data.collect import build

BUILT_AT = 100_000.0
OLD_END = 10_000.0


def _item(last_touch: float) -> Dict[str, Any]:
    return {"item": {"created_at": 0.0, "updated_at": last_touch}, "messages": [], "card_events": []}


def _get(monkeypatch, last_touch: float) -> List[str]:
    seen: List[str] = []
    held = {"built_at": BUILT_AT, "window": {"start": 0.0, "end": OLD_END}}
    monkeypatch.setattr(store, "load", lambda storage, key, version: dict(held, window=dict(held["window"])))
    monkeypatch.setattr(store, "save", lambda *a, **k: None)

    def rebuilt(*a: Any, **k: Any) -> Dict[str, Any]:
        seen.append("built")
        return {"window": {"start": 0.0, "end": last_touch}}

    monkeypatch.setattr(build, "build_run", rebuilt)
    ctx = SimpleNamespace(storage=None, activity=SimpleNamespace(huddle_item=lambda n: _item(last_touch)))
    asyncio.run(service.get_run(ctx, "huddle_item", "7"))
    return seen


def test_an_untouched_item_is_served_from_its_settled_snapshot(monkeypatch) -> None:
    assert _get(monkeypatch, OLD_END - 1800.0) == []


def test_an_item_touched_after_the_snapshot_is_rebuilt(monkeypatch) -> None:
    assert _get(monkeypatch, 9_000.0) == ["built"]

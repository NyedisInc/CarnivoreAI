
from __future__ import annotations

import asyncio
import json

import pytest

# ruff: noqa: F811
from src.core.swarm import admission, conflicts, settings as swarm_settings, spawn
from src.core.swarm.cards import capacity, dealer
from tests.python.swarm.cards.test_card_enforcement import _spawn, _spawn_world, caller, call, refused, world  # noqa: F401
from tests.python.swarm.cards.test_card_capacity import db, live


def _machine(monkeypatch, load1: float, load5: float, memory: float = 60.0) -> None:
    monkeypatch.setattr(admission, "measure", lambda: admission.Machine(load1, load5, 10, memory))


def test_a_spawn_is_refused_over_the_load_threshold_and_allowed_under_it(world, monkeypatch):
    w = world
    _, _, made = _spawn_world(w, monkeypatch)
    assert swarm_settings.SwarmConfig().max_children_per_parent is None and swarm_settings.SwarmConfig().max_live_bodies is None
    _machine(monkeypatch, 25.0, 22.0)
    with pytest.raises(spawn.SpawnRefused, match=r"system is pegged, try later \(retry_after 60 s\)"):
        asyncio.run(spawn.run(w.view, caller("boss"), _spawn(w)))
    assert not made and any(c[2].startswith("spawn_refused:") for c in w.port.cards)
    _machine(monkeypatch, 25.0, 12.0)
    first = asyncio.run(spawn.run(w.view, caller("boss"), _spawn(w)))
    _machine(monkeypatch, 5.0, 5.0, memory=4.0)
    with pytest.raises(spawn.SpawnRefused, match=r"system is pegged, try later \(retry_after 120 s\): only 4% of memory"):
        asyncio.run(spawn.run(w.view, caller("boss"), _spawn(w)))
    _machine(monkeypatch, 5.0, 5.0)
    for _ in range(6):
        asyncio.run(spawn.run(w.view, caller("boss"), _spawn(w)))
    assert first["agent_id"] == made[0]["id"] and len(made) == 7
    assert admission.refusal(admission.Machine(25.0, 22.0, 10, 60.0), 3, load_per_core_max=3.0) is None


def test_the_conflict_window_lowers_the_project_limit_and_lifts_when_clean(world, monkeypatch):
    w = world
    _spawn_world(w, monkeypatch)
    for slug in ("fixer", "builder", "kid"):
        live(w, slug)
    with db(w) as conn:
        assert capacity.slots(conn, 16, {}) == (None, None)
    out = None
    for kind in ("rebase_conflict", "push_rejected"):
        out = call(w, "fixer", "swarm_conflict", kind=kind)
    assert out["project_id"] == 16 and out["recent"] == 2 and out["throttled"] is False
    asyncio.run(spawn.run(w.view, caller("boss"), _spawn(w)))
    out = call(w, "kid", "swarm_conflict", kind="merge_lock_wait")
    assert out["throttled"] is True and out["limit"] == conflicts.THROTTLED_WORKERS
    with db(w) as conn:
        assert capacity.slots(conn, 16, {}) == (0, conflicts.THROTTLED_WORKERS)
    assert "Slots: 0 of 3 free" in dealer.request_text("Zeta", ["card_created"], [], [], slots=(0, 3))
    with pytest.raises(spawn.SpawnRefused, match="runs at most 3 agents until 30 minutes pass with none"):
        asyncio.run(spawn.run(w.view, caller("boss"), _spawn(w)))
    stamps = [t for t, _ in json.loads(conflicts.path().read_text())["16"]]
    later = max(stamps) + conflicts.WINDOW_S
    assert conflicts.current(16, now=later - 1) is not None and conflicts.current(16, now=later) is None
    assert "kind must be one of" in refused(w, "fixer", "swarm_conflict", kind="nope")


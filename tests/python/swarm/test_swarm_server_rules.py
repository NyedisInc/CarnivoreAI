
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.core.crosstalk import bus
from src.core.swarm import definition, settings as swarm_settings
from src.core.swarm.cards import lease, nudge


def test_the_caps_sentence_comes_from_the_swarm_settings_not_a_literal(monkeypatch):
    monkeypatch.setattr(swarm_settings, "read_current", lambda: swarm_settings.SwarmConfig(max_live_bodies=12, max_children_per_parent=3))
    text = definition.rank_rules("company")
    assert "12 agents in all and 3 under one parent" in text and "20" not in text
    monkeypatch.setattr(swarm_settings, "read_current", lambda: swarm_settings.SwarmConfig())
    assert "No hard cap on agents is set" in definition.rank_rules("alpha") and "or a whole company" in definition.rank_rules("alpha")


def test_a_holder_whose_turn_ended_is_nudged_once_and_a_working_or_asking_one_never(monkeypatch):
    nudge.reset()
    told = []

    async def tell(app_state, agent_id, text, *, ref, wake=True, **kw):
        told.append((agent_id, ref, wake, text))
        return "delivered"

    async def run_db(work):
        return {"id": 7, "torn_down_at": None, "state": "awake", "parent_id": None}

    class NoCards:
        async def cards(self, **kw):
            return []

    monkeypatch.setattr(nudge.deliver, "tell", tell)
    monkeypatch.setattr(nudge.body, "run_db", run_db)
    monkeypatch.setattr(nudge.card_port, "get", lambda: NoCards())
    beats = {7: lease.Beat(busy_at=1000.0), 8: lease.Beat(busy_at=1290.0), 9: lease.Beat(busy_at=1000.0, stopped=True)}
    monkeypatch.setattr(nudge.lease, "beat", lambda agent_id: beats.get(agent_id))
    leases = [{"id": 41, "holder": 7, "beat_at": 900.0}, {"id": 42, "holder": 8, "beat_at": 900.0}, {"id": 43, "holder": 9, "beat_at": 900.0}]
    assert asyncio.run(nudge.run(SimpleNamespace(), leases, now=1300.0)) == 1
    assert asyncio.run(nudge.run(SimpleNamespace(), leases, now=1400.0)) == 0
    assert told[0][:3] == (7, "card:41", False) and "swarm_card_finish" in told[0][3]


def test_a_card_in_review_with_no_report_nudges_its_last_holder_once(monkeypatch):
    nudge.reset()
    told = []

    async def tell(app_state, agent_id, text, *, ref, wake=True, **kw):
        told.append((agent_id, ref))
        return "delivered"

    async def run_db(work):
        return {"id": 5}

    class Review:
        async def cards(self, **kw):
            return [{"id": 50, "title": "t", "report_id": None, "last_holder": 5}, {"id": 51, "title": "t", "report_id": 3, "last_holder": 5}]

    monkeypatch.setattr(nudge.deliver, "tell", tell)
    monkeypatch.setattr(nudge.body, "run_db", run_db)
    monkeypatch.setattr(nudge.card_port, "get", lambda: Review())
    assert asyncio.run(nudge.run(SimpleNamespace(), [], now=0.0)) == 1
    assert asyncio.run(nudge.run(SimpleNamespace(), [], now=0.0)) == 0
    assert told == [(5, "card:50")]


@pytest.mark.parametrize("status, receipt", [("delivered", "delivered"), ("queued", "queued"), ("delivering", "queued"),
                                             ("held", "stuck"), ("failed", "stuck"), ("expired", "stuck")])
def test_a_crosstalk_send_receipt_names_delivered_queued_or_stuck(monkeypatch, status, receipt):
    rows = iter([{"status": "queued", "reason": None}, {"status": status, "reason": "receiver has an open dialog" if status == "held" else None}])
    monkeypatch.setattr(bus.store, "get", lambda message_id: next(rows))

    waits = iter([True, False])

    async def changed(timeout, since):
        return next(waits)

    monkeypatch.setattr(bus.store, "changed", changed)
    got = asyncio.run(bus.settle("m-1", timeout=1.0))
    assert got[0] == status and bus.receipt_of(got[0]) == receipt
    assert (got[1] == "receiver has an open dialog") == (status == "held")

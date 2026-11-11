
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.core.argent import classifier, classifier_auto, commits, notices, timeline
from tests.argent.test_argent_classifier import World, world  # noqa: F401


def auto(w: World, *made: Any, name: str = "carnivore_api") -> classifier.Outcome:
    return asyncio.run(classifier_auto.run(name, "api", "", None, made, chat=w.chat))


def current() -> list:
    return timeline.current("ten_1", "carnivore_api")


def test_unpicked_session_is_assigned_at_a_turn_end_with_a_commits_files(world: World) -> None:
    world.reply = {"scores": {"wi_story1": 0.93}}
    made = commits.Commit("abc1234", "fix login", ("src/auth_commit.py",), 1, "", "head")
    out = auto(world, made)
    assert (out.action, out.work_item_id) == ("switched", "wi_story1")
    assert [(d["work_item_id"], d["reason"]) for d in current()] == [("wi_story1", "classifier")]
    assert "src/auth_commit.py" in world.messages[0]
    assert len(world.notes) == 1
    world.reply = {"scores": {"wi_feat1": 0.95}}
    assert auto(world).action == "switched" and current()[0]["work_item_id"] == "wi_feat1"


@pytest.mark.parametrize("source", ["picker", "mcp-self", "card", "retag"])
def test_a_picked_work_item_is_never_overwritten(world: World, source: str) -> None:
    timeline.record("ten_1", "carnivore_api", "", "wi_feat1", source)
    world.reply = {"scores": {"wi_story1": 0.99}}
    out = auto(world)
    assert out.reason == "picked" and world.messages == [] and world.http == []
    assert [(d["work_item_id"], d["reason"]) for d in current()] == [("wi_feat1", source)]


def test_negative_control_the_guard_is_what_protects_a_pick(world: World) -> None:
    timeline.record("ten_1", "carnivore_api", "", "wi_feat1", "picker")
    world.reply = {"scores": {"wi_story1": 0.99}}
    out = asyncio.run(classifier.classify("carnivore_api", classifier.Signals("main"), chat=world.chat))
    assert out.action == "switched" and world.messages


def test_ask_every_time_only_suggests_and_the_notice_offers_one_click_change(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    classifier.set_ask_every_time(True)
    world.reply = {"scores": {"wi_story1": 0.95}}
    out = auto(world)
    assert out.action == "asked" and current() == [] and world.notes[0][4] is True
    monkeypatch.undo()
    raised: list = []
    from src.core.app_alerts import service
    monkeypatch.setattr(service, "raise_alert", lambda key, **kw: raised.append(kw))
    notices.classifier_fix("carnivore_api", "api", "Story", "", False)
    (action,) = raised[0]["actions"]
    assert action["id"] == "argent_change_story" and action["href"] == "#settings/features/argent/settings?session=carnivore_api"


def test_feature_off_makes_no_call(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timeline, "is_running", lambda: False)
    world.reply = {"scores": {"wi_story1": 0.99}}
    assert auto(world).reason == "feature_off" and world.messages == [] and world.http == [] and current() == []

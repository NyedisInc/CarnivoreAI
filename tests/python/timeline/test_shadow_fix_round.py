
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator, List
from unittest.mock import MagicMock

import pytest

from src.core import listing_attention
from src.core.attention import wiring_builders
from src.core.attention.evidence import Evidence, PaneVerdict
from src.core.attention.registry_index import registry_for_session
from src.core.attention.transcript_facts import TranscriptFacts
from src.core.mcp_health.history import reset_history
from src.core.product_identity import env_names
from src.core.session_status import LIVENESS_LIVE
from src.core.timeline import hot, parity
from src.core.timeline.pairs import PairBook
from tests.python.timeline.fold_fixtures import CONV, NOW, agent_launch, assistant, call, turn_end, user, write

PLAIN_SCREEN = PaneVerdict(permission_dialog=False, question_dialog=False, trust_dialog=False, resting_prompt=False)
RECORDS = [user(1, "run the agent"), assistant(2, [call("c1", "Agent")]), agent_launch(3, "c1", "a1"), turn_end(4, pending=1)]


@pytest.fixture
def shadow_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in env_names(hot.STATUS_SOURCE_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(hot, "_switch_on", lambda: True)
    for reset in (hot.reset_gate, hot.DRIVER.clear, hot.PAIRS.clear, reset_history):
        reset()
    with listing_attention._FACTS_MEMO_LOCK:
        listing_attention._FACTS_MEMO.clear()
    yield
    for reset in (hot.reset_gate, hot.DRIVER.clear, hot.PAIRS.clear):
        reset()


def _evidence(transcript: object) -> Evidence:
    return Evidence(tmux_liveness=LIVENESS_LIVE, agent_family="claude", registry=registry_for_session(tmux_name=None),
                    transcript=transcript, pane=PLAIN_SCREEN, now=NOW)


def _parity(clock: List[datetime], pairs: PairBook, store: Path) -> parity.Parity:
    return parity.Parity(clock=lambda: clock[0], min_comparisons=1, required_states=frozenset({"working_subagent"}),
                         enabled=lambda: True, pairs=pairs, store_path=lambda: store)


def test_item1_a_parity_bug_never_skips_the_status_publish(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    published: List[str] = []
    monkeypatch.setattr(wiring_builders, "to_display", lambda *a, **k: "working_subagent")
    monkeypatch.setattr(wiring_builders.session_change_notice, "publish_attention_status",
                        lambda _app, _mgr, session_id, **k: published.append(session_id))
    transcript = TranscriptFacts(verdict="found")
    pairs = PairBook()
    pairs.file(transcript, transcript, 1)
    counter = _parity([NOW], pairs, tmp_path / "parity.json")
    monkeypatch.setattr(wiring_builders.timeline_parity, "PARITY", counter)
    monkeypatch.setattr(parity, "compare", MagicMock(side_effect=TypeError("a bug in the shadow")))
    effects = MagicMock()
    effects.instance_for.return_value = (None, None)
    hooks = wiring_builders.ObservationHooks(*(MagicMock() for _ in range(8)))
    manager = SimpleNamespace(_is_unread=lambda *a: False)
    on_observation = wiring_builders.make_on_observation(manager, SimpleNamespace(), effects, hooks, None)
    evidence = _evidence(transcript)
    verdict = SimpleNamespace(state="busy", reason="r", tier="transcript", activity_hint=None)
    on_observation(SimpleNamespace(session_id="ses_a", key="k"),
                   SimpleNamespace(evidence=evidence, verdict=verdict, stale=False, observed_at=0))
    assert published == ["ses_a"]


def test_item2_the_hook_cannot_escape_the_listing_read(tmp_path: Path, shadow_on: None,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    write(path, RECORDS)
    monkeypatch.setattr(hot, "_switch_on", MagicMock(side_effect=TypeError("a broken switch read")))
    hot.reset_gate()
    facts = listing_attention._facts_for_path(str(path), now=NOW)
    assert facts.found
    assert listing_attention._FACTS_MEMO[str(path)][2] is facts


def test_item3_a_reader_behind_the_cursor_is_raced_not_reseeded(tmp_path: Path, shadow_on: None) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    lines = write(path, RECORDS)
    small = lines[1][2]
    assert hot.DRIVER.facts_at(str(path), os.path.getsize(path), now=NOW) is not None
    kept = hot.DRIVER._files[os.path.realpath(path)]
    assert hot.DRIVER.facts_at(str(path), small, now=NOW) is None
    assert hot.DRIVER._files[os.path.realpath(path)] is kept and kept.state.cursor == os.path.getsize(path)


def test_item6_the_floor_counts_a_pair_once_a_day_and_races_have_their_own_bucket(tmp_path: Path, shadow_on: None) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    write(path, RECORDS)
    legacy = listing_attention._facts_for_path(str(path), now=NOW)
    clock = [datetime(2026, 11, 1, 12, tzinfo=timezone.utc)]
    counter = _parity(clock, hot.PAIRS, tmp_path / "parity.json")
    for _ in range(3):
        counter.on_observation("ses_a", _evidence(legacy), "working_subagent")
    raced = listing_attention.transcript_facts_for
    hot.PAIRS.mark_raced(raced, 1)  # type: ignore[arg-type]
    counter.on_observation("ses_b", _evidence(raced), "working_subagent")
    day = counter.snapshot()["days"][0]
    assert day["comparisons"] == 3 and day["transcript_decided"] == 1, day
    assert day["raced"] == 1 and day["unpaired"] == 0, day
    clock[0] += timedelta(days=1)
    counter.on_observation("ses_a", _evidence(legacy), "working_subagent")
    assert counter.snapshot()["days"][0]["transcript_decided"] == 1


def test_item5_day_tallies_survive_a_restart(tmp_path: Path, shadow_on: None) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    write(path, RECORDS)
    legacy = listing_attention._facts_for_path(str(path), now=NOW)
    store = tmp_path / "pipeline-plugins" / "timeline-parity.json"
    clock = [datetime(2026, 11, 1, 12, tzinfo=timezone.utc)]
    _parity(clock, hot.PAIRS, store).on_observation("ses_a", _evidence(legacy), "working_subagent")
    assert store.exists()
    day = _parity(clock, PairBook(), store).snapshot()["days"][0]
    assert day["day"] == "2026-11-01" and day["comparisons"] == 1 and day["canary"]["real"] == 1, day


def test_any_shadow_failure_leaves_the_listing_read_its_legacy_answer(tmp_path: Path, shadow_on: None,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    write(path, RECORDS)
    monkeypatch.setattr(hot.DRIVER, "facts_at", MagicMock(side_effect=RuntimeError("an unexpected shadow failure")))
    facts = listing_attention._facts_for_path(str(path), now=NOW)
    assert facts.found
    assert listing_attention._FACTS_MEMO[str(path)][2] is facts

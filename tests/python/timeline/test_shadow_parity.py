
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest

from src.core import listing_attention
from src.core.attention.display import to_display
from src.core.attention.evidence import Evidence, PaneVerdict
from src.core.attention.registry_index import registry_for_session
from src.core.attention.resolve import resolve_attention
from src.core.mcp_health.history import reset_history
from src.core.product_identity import env_names
from src.core.session_status import LIVENESS_LIVE, STATUS_UNKNOWN
from src.core.timeline import hot
from src.core.timeline.parity import CLASS_REAL, Parity
from tests.python.timeline.fold_fixtures import CONV, NOW, agent_launch, assistant, call, turn_end, user, write


@pytest.fixture
def shadow_on(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in env_names(hot.STATUS_SOURCE_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(hot, "_switch_on", lambda: True)
    hot.reset_gate()
    hot.DRIVER.clear()
    hot.PAIRS.clear()
    reset_history()
    with listing_attention._FACTS_MEMO_LOCK:
        listing_attention._FACTS_MEMO.clear()
    yield
    hot.reset_gate()
    hot.DRIVER.clear()
    hot.PAIRS.clear()


PLAIN_SCREEN = PaneVerdict(permission_dialog=False, question_dialog=False, trust_dialog=False, resting_prompt=False)


def _evidence(transcript: object) -> Evidence:
    return Evidence(tmux_liveness=LIVENESS_LIVE, agent_family="claude", registry=registry_for_session(tmux_name=None),
                    transcript=transcript, pane=PLAIN_SCREEN, now=NOW)


def test_canary_reads_real_one_and_a_day_without_comparisons_does_not_count(tmp_path: Path, shadow_on: None) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    write(path, [user(1, "run the agent"), assistant(2, [call("c1", "Agent")]),
                 agent_launch(3, "c1", "a1"), turn_end(4, pending=1)])
    legacy = listing_attention._facts_for_path(str(path), now=NOW)
    assert hot.PAIRS.find(legacy) is not None, "the listing's read did not file a fold twin"

    evidence = _evidence(legacy)
    display = to_display(resolve_attention(evidence), unread=False, tmux_status=STATUS_UNKNOWN)
    clock: List[datetime] = [datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)]
    parity = Parity(clock=lambda: clock[0], min_comparisons=1, required_states=frozenset({display}),
                    enabled=lambda: True, store_path=lambda: tmp_path / "timeline-parity.json")

    parity.on_observation("ses_a", _evidence(dataclasses.replace(legacy)), display)
    clock[0] += timedelta(days=1)
    parity.on_observation("ses_a", evidence, display)

    today, empty_day = parity.snapshot()["days"]
    assert empty_day["comparisons"] == 0 and empty_day["unpaired"] == 1
    assert empty_day["counted"] is False, "a day that compared nothing was counted"
    assert today["canary"].get(CLASS_REAL) == 1, f"the canary did not read real: 1 ({today['canary']})"
    assert today["canary_light"].get(CLASS_REAL) == 1, f"the light canary did not read real: 1 ({today['canary_light']})"
    assert today["comparisons"] == 1 and today["classes"].get(CLASS_REAL, 0) == 0, today
    assert today["transcript_decided"] == 1, today
    assert today["counted"] is True, today
    assert parity.snapshot()["counted_days"] == 1

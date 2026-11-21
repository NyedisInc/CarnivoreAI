
from __future__ import annotations

import os
from pathlib import Path

from src.core.timeline import agent_tail, model
from src.core.timeline.model import Kind
from tests.python.timeline.exposure_helpers import CONV, append, turn, user
from tests.python.timeline.test_t5_fix_hotpath import _agent


def _many_agents(main: Path, count: int) -> None:
    for n in range(count):
        path = _agent(main, f"a{n:04d}")
        append(path, [user(1, f"agent {n}")])
        os.utime(path, (1_700_000_000 + n, 1_700_000_000 + n))


def test_state_files_are_bounded_newest_first_with_a_total_and_a_more_flag(api) -> None:
    client, main = api
    append(main, turn(0, "a"))
    count = agent_tail.MAX_STATE_AGENT_FILES + 8
    _many_agents(main, count)
    answer = client.get("/api/v1/sessions/ses_1/timeline/state").json()
    shown = set(answer["files"]) - {"main"}
    assert "main" in answer["files"]
    assert len(shown) == agent_tail.MAX_STATE_AGENT_FILES
    assert shown == {f"a{n:04d}" for n in range(count - agent_tail.MAX_STATE_AGENT_FILES, count)}
    assert answer["files_total"] == count + 1 and answer["files_more"] is True


def test_state_with_few_agent_files_lists_all_and_is_not_more(api) -> None:
    client, main = api
    append(main, turn(0, "a"))
    _many_agents(main, 3)
    answer = client.get("/api/v1/sessions/ses_1/timeline/state").json()
    assert set(answer["files"]) == {"main", "a0000", "a0001", "a0002"}
    assert answer["files_total"] == 4 and answer["files_more"] is False


def test_suppressed_is_a_trace_event_so_the_default_level_hides_it() -> None:
    assert model.KIND_LEVELS[Kind.SUPPRESSED] == model.LEVEL_TRACE
    assert model.KIND_LEVELS[Kind.SUPPRESSED] > 2


from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pytest

from src.api import asleep_offloaded
from src.core.backup_health import offloaded_marker
from src.models.records import SessionRecord


def pair(uuid: str, conversation: Optional[str], *, asleep: bool = True):
    return {"session_uuid": uuid, "claude_session_uuid": conversation}, SessionRecord.model_construct(session_uuid=uuid, offloaded=None, asleep=asleep)


def stamp(pairs, state: Path, on_disk=frozenset()) -> List[Optional[bool]]:
    asleep_offloaded.stamp_offloaded([p[0] for p in pairs], [p[1] for p in pairs], state, on_disk)
    return [p[1].offloaded for p in pairs]


@pytest.fixture()
def state(tmp_path: Path) -> Path:
    return tmp_path


def test_a_sleeper_whose_conversation_the_marker_holds_is_offloaded_and_the_rest_are_not(state: Path) -> None:
    assert offloaded_marker.write(state, [("c1", ["S1"], 10), ("c2", ["S2"], 20)])
    pairs = [pair("S1", "c1"), pair("S2", "c2"), pair("S9", "c9"), pair("S8", None), pair("S1b", "c1", asleep=False)]
    assert stamp(pairs, state) == [True, True, False, False, None]


def test_a_conversation_whose_transcript_is_on_disk_is_not_offloaded(state: Path) -> None:
    assert offloaded_marker.write(state, [("c1", ["S1"], 10)])
    assert stamp([pair("S1", "c1")], state, on_disk=frozenset({"c1"})) == [False]


def test_an_absent_marker_says_false_and_an_unreadable_one_says_not_measured_and_logs_once(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert stamp([pair("S1", "c1")], state) == [False]
    (state / offloaded_marker.MARKER_FILE).write_text("not json", encoding="utf-8")
    logged: List[str] = []
    monkeypatch.setattr(asleep_offloaded.logger, "error", lambda event, **kw: logged.append(event))
    monkeypatch.setattr(offloaded_marker.logger, "error", lambda event, **kw: logged.append(event))
    monkeypatch.setattr(asleep_offloaded, "_logged_unreadable", None)
    for _ in range(3):
        assert stamp([pair("S1", "c1")], state) == [None]
    assert logged == ["offloaded_marker_unreadable_for_listing"]
    (state / offloaded_marker.MARKER_FILE).write_text("still not json!", encoding="utf-8")
    stamp([pair("S1", "c1")], state)
    assert len(logged) == 2

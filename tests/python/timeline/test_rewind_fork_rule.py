
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.bookmarks.transcript_index import build_index
from src.core.timeline import rewind
from tests.python.timeline.exposure_helpers import append, assistant, user

LIVE_OPENERS = [
    ("typed", "redo it", {}),
    ("slash", "<command-name>/clear</command-name><command-message>clear</command-message>", {"isMeta": True}),
    ("caveat", "<local-command-caveat>Caveat: ran local commands</local-command-caveat>", {"isMeta": True}),
    ("image", [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}], {}),
    ("task", "<task-notification><task-id>b1</task-id><status>completed</status></task-notification>",
     {"origin": {"kind": "task-notification"}}),
]


def _u(second: int, uuid: str, parent: Any, content: Any = "x", **extra: Any) -> Dict[str, Any]:
    return user(second, content, uuid=uuid, parentUuid=parent, **extra)


def _a(second: int, uuid: str, parent: Any, blocks: Any = None, msg: str = "") -> Dict[str, Any]:
    return assistant(second, blocks or [{"type": "text", "text": "ok"}], msg=msg or f"m-{uuid}", stop="end_turn", uuid=uuid, parentUuid=parent)


def _forks(tmp_path: Path, records: List[Dict[str, Any]]) -> List[str]:
    path = tmp_path / "c.jsonl"
    append(path, records)
    return [fork.fork_uuid for fork in rewind.compute(build_index(path)).forks]


def test_an_interrupted_assistant_stream_is_no_fork(tmp_path: Path) -> None:
    thinking = [{"type": "thinking", "thinking": "hm"}]
    records = [_u(0, "U1", None), _a(1, "A1", "U1"), _a(2, "AX", "A1", thinking), _u(5, "U2", "A1", "again"), _a(6, "A2", "U2")]
    assert _forks(tmp_path, records) == []


@pytest.mark.parametrize("name,content,extra", LIVE_OPENERS, ids=[o[0] for o in LIVE_OPENERS])
def test_a_rewind_is_a_fork_whatever_turn_the_live_side_opens_with(tmp_path: Path, name: str, content: Any, extra: Dict[str, Any]) -> None:
    records = [_u(0, "U1", None), _a(1, "A1", "U1"), _u(2, "U2", "A1", "first try"), _a(3, "A2", "U2"), _u(10, "U3", "A1", content, **extra),
               _a(11, "A3", "U3")]
    assert _forks(tmp_path, records) == ["A1"], name


def test_a_resend_across_a_compaction_is_no_fork(tmp_path: Path) -> None:
    boundary = {"type": "system", "subtype": "compact_boundary", "uuid": "B1", "parentUuid": None, "logicalParentUuid": "A1",
                "timestamp": "2026-11-01T10:00:09.000Z", "compactMetadata": {"trigger": "auto", "preTokens": 9}}
    records = [_u(0, "U1", None), _a(1, "A1", "U1"), _u(2, "X1", "A1", "resent"), boundary, _u(10, "Q1", "B1", "next"), _a(11, "QA1", "Q1")]
    assert _forks(tmp_path, records) == []

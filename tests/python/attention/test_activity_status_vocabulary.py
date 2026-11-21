from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import get_args

import pytest

SRC = Path(__file__).resolve().parents[3] / "src"
EIGHT = {"working", "working_subagent", "question", "notice", "finished_unread", "idle", "dead", "unknown"}


def test_openapi_activity_status_is_an_enum_of_the_eight_states() -> None:
    from src.main import app

    schemas = app.openapi()["components"]["schemas"]
    prop = schemas["SessionInfo"]["properties"]["activity_status"]
    values = prop.get("enum") or schemas[prop["$ref"].rsplit("/", 1)[-1]]["enum"] if ("enum" in prop or "$ref" in prop) else None
    assert values is not None, f"activity_status is not an enum: {prop}"
    assert set(values) == EIGHT and len(values) == 8


def test_literal_matches_the_status_module_constants() -> None:
    from src.core.session_status import ALL_ACTIVITY_STATUSES
    from src.models.activity_status import ActivityStatus

    assert set(get_args(ActivityStatus)) == EIGHT == set(ALL_ACTIVITY_STATUSES)


def test_named_sets_are_subsets_and_the_huddle_set_has_its_own_name() -> None:
    from src.models import activity_status as vocab

    for name in ("RESTING", "BUSY", "BLOCKED_ON_OWNER", "TURN_OVER"):
        assert getattr(vocab, name) <= EIGHT, name
    assert vocab.RESTING == {"idle", "finished_unread"}
    assert vocab.TURN_OVER == vocab.RESTING | {"question", "notice"}


@pytest.mark.parametrize(
    ("status", "gate", "blocked"),
    [("question", "ready", True), ("idle", "awaiting_startup_prompt", True), ("idle", "ready", False), ("working", "ready", False)],
)
def test_blocked_on_owner_predicate(status: str, gate: str, blocked: bool) -> None:
    from types import SimpleNamespace

    from src.models.activity_status import blocked_on_owner

    assert blocked_on_owner(SimpleNamespace(activity_status=status, startup_gate=gate)) is blocked


_BLOCKED_COPY = re.compile(r"""activity_status\s*==\s*["']question["']\s*or\s*\w+\.startup_gate""")
_ALLOWED = {
    "src/models/activity_status.py",
    "src/core/session_one_shot_gate.py",
    "src/core/swarm/settings.py",
}


def _hand_set_lines(source: str) -> list[int]:
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Tuple, ast.Set, ast.List)):
            members = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if {"idle", "finished_unread"} <= members:
                hits.append(node.lineno)
    return hits


def _py_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if str(p.relative_to(SRC.parent)) not in _ALLOWED]


def test_hand_set_pattern_can_fail() -> None:
    assert _hand_set_lines('X = ("idle", "finished_unread")\n') == [1]
    assert _hand_set_lines("Y = frozenset({'finished_unread','idle'})\n") == [1]
    assert _hand_set_lines('Z = (\n    "idle",\n    "finished_unread",\n    "question",\n)\n') == [1]
    assert _hand_set_lines("if status in RESTING:\n    pass\n") == []
    assert _BLOCKED_COPY.search('x = info.activity_status == "question" or info.startup_gate != "ready"')
    assert not _BLOCKED_COPY.search("if blocked_on_owner(info):")


def test_no_hand_built_status_set_outside_the_vocabulary() -> None:
    hits = [f"{p.relative_to(SRC.parent)}:{n}" for p in _py_files() for n in _hand_set_lines(p.read_text(encoding="utf-8"))]
    assert not hits, "hand-built status sets, use src.models.activity_status: " + ", ".join(hits)


def test_blocked_on_owner_check_is_not_copied() -> None:
    hits = [str(p.relative_to(SRC.parent)) for p in _py_files() if _BLOCKED_COPY.search(p.read_text(encoding="utf-8"))]
    assert not hits, "copies of the blocked-on-owner check: " + ", ".join(hits)


def test_typescript_union_matches_the_python_literal() -> None:
    from src.models.activity_status import ActivityStatus

    ts = (SRC.parent / "web" / "src" / "lib" / "activity-status.ts").read_text(encoding="utf-8")
    body = re.search(r"ACTIVITY_STATUSES = \[(.*?)\] as const", ts, re.S)
    assert body is not None, "ACTIVITY_STATUSES not found in activity-status.ts"
    assert re.findall(r"'(\w+)'", body.group(1)) == list(get_args(ActivityStatus))


def test_an_unrecognized_status_from_a_peer_row_reads_as_unknown_not_a_rejection() -> None:
    from src.models.sessions import Session, SessionInfo

    info = SessionInfo.model_validate({"session": Session(id="ses_x", working_dir="/p").model_dump(), "activity_status": "hibernating"})
    assert info.activity_status == "unknown"
    assert SessionInfo.model_validate({"session": Session(id="ses_x", working_dir="/p").model_dump(), "activity_status": "idle"}).activity_status == "idle"

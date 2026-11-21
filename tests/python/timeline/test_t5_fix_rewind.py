
from __future__ import annotations

from typing import Any, Dict, List

from tests.python.timeline.exposure_helpers import CONV, append, assistant, call, user


def _url(path: str) -> str:
    return f"/api/v1/sessions/ses_1/timeline/{path}"


def _rec(second: int, uuid: str, parent: Any, kind: str = "user", text: str = "x") -> Dict[str, Any]:
    if kind == "user":
        return user(second, text, uuid=uuid, parentUuid=parent)
    return assistant(second, [{"type": "text", "text": text}], msg=f"m-{uuid}", stop="end_turn", uuid=uuid, parentUuid=parent)


def _rewound(main: Any) -> None:
    append(main, [_rec(0, "U1", None), _rec(1, "A1", "U1", "assistant"), _rec(2, "U2", "A1"), _rec(3, "A2", "U2", "assistant"),
                  _rec(10, "U3", "A1"), _rec(11, "A3", "U3", "assistant")])


def _res(second: int, call_id: str, uuid: str, parent: Any) -> Dict[str, Any]:
    return user(second, [{"type": "tool_result", "tool_use_id": call_id, "content": "ok"}], uuid=uuid, parentUuid=parent)


def _kinds(answer: Dict[str, Any]) -> List[str]:
    return [e["kind"] for e in answer["events"]]


def test_a_rewound_branch_is_hidden_behind_one_divider_by_default(api) -> None:
    client, main = api
    _rewound(main)
    shown = client.get(_url("events"), params={"after": f"{CONV}:main:0:", "level": 2}).json()
    assert _kinds(shown).count("rewind") == 1 and _kinds(shown).count("prompt") == 2 and _kinds(shown).count("reply") == 2
    divider = next(e for e in shown["events"] if e["kind"] == "rewind")
    assert divider["data"]["fork_uuid"] == "A1" and divider["data"]["abandoned_from"] < divider["data"]["abandoned_to"]
    assert not any(e.get("abandoned") for e in shown["events"])
    kinds = _kinds(shown)
    assert kinds[kinds.index("rewind") + 1:][:2] == ["prompt", "reply"]


def test_include_abandoned_shows_the_branch_flagged_and_keeps_the_divider(api) -> None:
    client, main = api
    _rewound(main)
    shown = client.get(_url("events"), params={"after": f"{CONV}:main:0:", "include_abandoned": "true"}).json()
    assert _kinds(shown).count("prompt") == 3 and _kinds(shown).count("reply") == 3 and _kinds(shown).count("rewind") == 1
    flagged = [e for e in shown["events"] if e.get("abandoned")]
    divider_at = next(number for number, e in enumerate(shown["events"]) if e["kind"] == "rewind")
    assert [e["kind"] for e in flagged] == ["prompt", "reply", "turn_end"] and shown["events"].index(flagged[-1]) < divider_at


def test_the_newest_window_read_applies_the_rule_too(api) -> None:
    client, main = api
    _rewound(main)
    window = client.get(_url("events")).json()
    assert _kinds(window).count("prompt") == 2 and _kinds(window).count("rewind") == 1


def test_parallel_tool_results_are_not_a_fork_and_a_compaction_is_crossed(api) -> None:
    client, main = api
    append(main, [_rec(0, "P1", None), assistant(1, [call("c1", "Bash")], uuid="PA1", parentUuid="P1"),
                  assistant(2, [call("c2", "Bash")], uuid="PA2", parentUuid="PA1"),
                  _res(3, "c1", "PR1", "PA1"), _res(4, "c2", "PR2", "PA2"),
                  _rec(5, "PA3", "PR2", "assistant"),
                  {"type": "system", "subtype": "compact_boundary", "uuid": "B1", "parentUuid": None, "logicalParentUuid": "PA3",
                   "timestamp": "2026-11-01T10:00:09.000Z", "compactMetadata": {"trigger": "auto", "preTokens": 9}},
                  _rec(10, "Q1", "B1"), _rec(11, "QA1", "Q1", "assistant")])
    shown = client.get(_url("events"), params={"after": f"{CONV}:main:0:", "level": 3}).json()
    assert "rewind" not in _kinds(shown) and _kinds(shown).count("tool_result") == 2 and not any(e.get("abandoned") for e in shown["events"])
    both = client.get(_url("events"), params={"after": f"{CONV}:main:0:", "level": 3, "include_abandoned": "true"}).json()
    assert [e["id"] for e in both["events"]] == [e["id"] for e in shown["events"]]


def test_a_dangling_parent_hides_nothing(api) -> None:
    client, main = api
    append(main, [_rec(0, "D1", "not-in-this-file"), _rec(1, "DA1", "D1", "assistant"), _rec(2, "DB1", "D1", "assistant"),
                  _rec(3, "D2", None), _rec(4, "DA2", "D2", "assistant")])
    shown = client.get(_url("events"), params={"after": f"{CONV}:main:0:"}).json()
    assert _kinds(shown).count("prompt") == 2 and _kinds(shown).count("reply") == 3 and "rewind" not in _kinds(shown)

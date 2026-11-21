
from __future__ import annotations

from typing import Any, Dict, List

from tests.python.timeline.exposure_helpers import CONV, append, assistant, call, user
from tests.python.timeline.test_t5_fix_rewind import _rec, _res, _url


def _kinds(answer: Dict[str, Any]) -> List[str]:
    return [e["kind"] for e in answer["events"]]


def _read(client: Any, **params: Any) -> Dict[str, Any]:
    return client.get(_url("events"), params={"after": f"{CONV}:main:0:", "level": 3, **params}).json()


def _window(main: Any, finish: bool) -> None:
    records = [_rec(0, "P0", None), _rec(0, "PA0", "P0", "assistant"), _rec(0, "P1", "PA0"),
               assistant(1, [call("c1", "Bash")], msg="m1", uuid="PA1", parentUuid="P1"),
               assistant(2, [call("c2", "Bash")], msg="m1", uuid="PA2", parentUuid="PA1"),
               _res(3, "c1", "PR1", "PA1")]
    if finish:
        records.append(_res(4, "c2", "PR2", "PA2"))
    append(main, records)


def test_a_cut_at_the_parallel_call_window_is_no_fork_and_drops_no_call(api) -> None:
    client, main = api
    _window(main, finish=False)
    shown = _read(client)
    assert "rewind" not in _kinds(shown) and _kinds(shown).count("tool_call") == 2
    assert not any(e.get("abandoned") for e in shown["events"])
    append(main, [_res(4, "c2", "PR2", "PA2")])
    full = _read(client)
    assert "rewind" not in _kinds(full) and _kinds(full).count("tool_call") == 2 and _kinds(full).count("tool_result") == 2


def test_a_real_rewind_still_forks_when_the_live_branch_opens_with_a_prompt(api) -> None:
    client, main = api
    _window(main, finish=True)
    append(main, [_rec(20, "U2", "PA0"), _rec(21, "A2", "U2", "assistant")])
    shown = _read(client)
    assert _kinds(shown).count("rewind") == 1 and _kinds(shown).count("tool_call") == 0
    both = _read(client, include_abandoned="true")
    assert _kinds(both).count("tool_call") == 2 and sum(1 for e in both["events"] if e.get("abandoned")) >= 2


def test_a_split_assistant_message_off_the_live_path_is_not_an_abandoned_branch(api) -> None:
    client, main = api
    append(main, [_rec(0, "P1", None), assistant(1, [{"type": "text", "text": "a"}], msg="m1", uuid="A1", parentUuid="P1"),
                  assistant(2, [{"type": "text", "text": "b"}], msg="m1", uuid="A1b", parentUuid="A1"),
                  _rec(3, "U2", "A1"), _rec(4, "A2", "U2", "assistant")])
    shown = _read(client)
    assert "rewind" not in _kinds(shown) and _kinds(shown).count("reply") == 3


def test_the_divider_sits_on_the_first_live_line_that_makes_an_event(api) -> None:
    client, main = api
    _window(main, finish=True)
    attach = {"type": "attachment", "uuid": "ATT", "parentUuid": "PA0", "timestamp": "2026-11-01T10:00:20.000Z", "attachment": {"type": "ultra_effort_enter"}}
    append(main, [attach, _rec(21, "U2", "ATT"), _rec(22, "A2", "U2", "assistant")])
    shown = _read(client)
    kinds = _kinds(shown)
    assert kinds.count("rewind") == 1 and kinds[kinds.index("rewind") + 1] == "prompt"


def test_an_abandoned_branch_that_opens_with_an_attachment_then_a_prompt_is_a_fork(api) -> None:
    client, main = api
    attach = {"type": "attachment", "uuid": "ATT", "parentUuid": "A1", "timestamp": "2026-11-01T10:00:02.000Z", "attachment": {"type": "ultra_effort_enter"}}
    append(main, [_rec(0, "U1", None), _rec(1, "A1", "U1", "assistant"), attach, _rec(3, "U2", "ATT"), _rec(4, "A2", "U2", "assistant"),
                  _rec(10, "U3", "A1"), _rec(11, "A3", "U3", "assistant")])
    shown = _read(client)
    assert _kinds(shown).count("rewind") == 1 and _kinds(shown).count("prompt") == 2
    assert _kinds(_read(client, include_abandoned="true")).count("prompt") == 3


def test_a_system_rooted_branch_whose_live_side_opens_with_an_assistant_record_is_not_a_fork(api) -> None:
    client, main = api
    system = {"type": "system", "uuid": "SYS", "parentUuid": "U1", "timestamp": "2026-11-01T10:00:01.000Z", "subtype": "x"}
    append(main, [_rec(0, "U1", None), system, _rec(2, "U2", "SYS"), _rec(3, "A2", "U2", "assistant"),
                  _rec(10, "A1", "U1", "assistant"), _rec(11, "U3", "A1")])
    shown = _read(client)
    assert "rewind" not in _kinds(shown) and _kinds(shown).count("prompt") == 3 and not any(e.get("abandoned") for e in shown["events"])


from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from tests.python.timeline.exposure_helpers import (
    CONV, append, assistant, build_index as _index, call, result, turn, user,
)


def _url(path: str) -> str:
    return f"/api/v1/sessions/ses_1/timeline/{path}"


def _ids(page: Dict[str, Any]) -> List[str]:
    return [e["id"] for e in page["events"]]


def test_backward_pages_by_turn_join_into_the_forward_read(api, tmp_path: Path) -> None:
    client, main = api
    for index in range(5):
        append(main, turn(10 * index, str(index)))
    _index(tmp_path / "state", main)
    newest = client.get(_url("events"), params={"limit": 2}).json()
    assert newest["indexing"] is None and newest["next_before"] is not None and newest["next"] and newest["end"] is True
    middle = client.get(_url("events"), params={"limit": 2, "before_turn": newest["next_before"]}).json()
    oldest = client.get(_url("events"), params={"limit": 2, "before_turn": middle["next_before"]}).json()
    assert oldest["next_before"] is None and middle["next"] is None
    backward = _ids(oldest) + _ids(middle) + _ids(newest)
    forward = _ids(client.get(_url("events"), params={"after": f"{CONV}:main:0:"}).json())
    assert backward == forward and len(backward) == 20
    more = client.get(_url("events"), params={"after": newest["next"]}).json()
    assert more["events"] == [] and more["end"] is True


def test_one_turn_by_id_and_the_turn_and_thread_rows(api, tmp_path: Path) -> None:
    client, main = api
    append(main, turn(0, "a") + [user(10, "b"), assistant(11, [call("c1", "Agent")]),
                                 result(12, "c1", isAsync=True, agentId="a1", status="async_launched")] + turn(20, "c"))
    _index(tmp_path / "state", main)
    turns = client.get(_url("turns")).json()
    assert [t["origin"] for t in turns["turns"]][:1] and len(turns["turns"]) == 3 and turns["indexing"] is None
    second = sorted(t["turn"] for t in turns["turns"])[1]
    one = client.get(_url("events"), params={"turn": second, "level": 3}).json()
    assert one["events"] and {e["turn"] for e in one["events"]} == {second} and "tool_call" in {e["kind"] for e in one["events"]}
    assert client.get(_url("events"), params={"turn": 1}).status_code == 404
    threads = client.get(_url("threads")).json()
    assert [(t["kind"], t["status"]) for t in threads["threads"]] == [("agent", "running")]


def test_a_half_indexed_conversation_says_how_far_and_pages_nothing_it_cannot(api, tmp_path: Path) -> None:
    client, main = api
    for index in range(3):
        append(main, turn(10 * index, str(index)))
    one_turn = len(main.read_bytes()) // 3
    _index(tmp_path / "state", main, upto=one_turn)
    newest = client.get(_url("events")).json()
    assert newest["indexing"]["pct"] == 33 and newest["end"] is True and newest["next_before"] is None
    assert client.get(_url("events"), params={"before_turn": 1}).json()["events"] == []


from __future__ import annotations

import json

from tests.python.timeline.exposure_helpers import (
    CONV, SESSION, append, assistant, call, result, turn, user,
)

KEY = "ghp_" + "a1B2c3D4" * 5


def _url(path: str) -> str:
    return f"/api/v1/sessions/ses_1/timeline/{path}"


def test_state_reports_the_open_agents_and_the_last_turn_end(api) -> None:
    client, main = api
    append(main, [user(0, "go"), assistant(1, [call("c1", "Agent")]), result(2, "c1", isAsync=True, agentId="a1", status="async_launched")])
    body = client.get(_url("state")).json()
    assert body["source"] == "read" and body["conv"] == CONV and body["session_uuid"] == SESSION
    assert body["transcript"]["open_agents"] == 1 and body["transcript"]["coverage"] == "whole"
    assert body["live"] is None and body["pos"]["cursor"].startswith(f"{CONV}:main:")


def test_events_page_forward_by_cursor_and_filter_by_kind_and_level(api) -> None:
    client, main = api
    append(main, turn(0, "a") + turn(10, "b"))
    first = client.get(_url("events"), params={"after": f"{CONV}:main:0:", "level": 3}).json()
    kinds = [e["kind"] for e in first["events"]]
    assert kinds[:2] == ["prompt", "reply"] and "turn_end" in kinds and first["end"] is True and first["reset"] is None
    only = client.get(_url("events"), params={"after": f"{CONV}:main:0:", "kinds": "reply,prompt"}).json()
    assert {e["kind"] for e in only["events"]} == {"prompt", "reply"}
    append(main, turn(20, "c"))
    more = client.get(_url("events"), params={"after": first["next"]}).json()
    assert [e["kind"] for e in more["events"]][0] == "prompt" and more["next"] != first["next"]
    assert all(set(e) >= {"id", "level", "pos", "kind", "data"} for e in more["events"])
    assert not any("prompt c" in json.dumps(e) for e in more["events"])


def test_events_without_a_cursor_read_the_newest_window_and_say_the_index_has_not_run(api) -> None:
    client, main = api
    append(main, turn(0, "a"))
    answer = client.get(_url("events")).json()
    assert [e["kind"] for e in answer["events"]][:2] == ["prompt", "reply"] and answer["indexing"] == {"pct": None}
    assert answer["next"].startswith(f"{CONV}:main:")
    assert client.get(_url("turns")).json()["turns"] == [] and client.get(_url("threads")).json()["threads"] == []


def test_a_stale_cursor_answers_reset_and_bad_input_is_refused(api) -> None:
    client, main = api
    append(main, turn(0, "a"))
    held = client.get(_url("events"), params={"after": f"{CONV}:main:0:"}).json()["next"]
    main.write_bytes(b"")
    append(main, [user(0, "a longer different first line than the old one had"), user(1, "again")] * 3)
    assert client.get(_url("events"), params={"after": held}).json()["reset"] == "file_rewritten"
    assert client.get(_url("events"), params={"after": "nonsense"}).status_code == 422
    assert client.get(_url("events"), params={"kinds": "prompt,nope"}).status_code == 422
    assert client.get(_url("events"), params={"after": "other:main:0:"}).status_code == 404
    assert client.get(_url("events"), params={"thread": "agent:missing"}).status_code == 404


def test_one_event_body_is_read_from_the_file_redacted_and_cut(api) -> None:
    client, main = api
    append(main, [user(0, f"deploy with {KEY} please"), assistant(1, [{"type": "text", "text": "ok " * 40000}], stop="end_turn")])
    listed = client.get(_url("events"), params={"after": f"{CONV}:main:0:"}).json()["events"]
    prompt, reply = listed[0], listed[1]
    got = client.get(_url(f"events/{prompt['id']}")).json()
    assert "deploy with" in got["body"] and KEY not in got["body"] and got["event"]["id"] == prompt["id"]
    big = client.get(_url(f"events/{reply['id']}")).json()
    assert big["truncated"] is True and len(big["body"]) == 64 * 1024
    stale = prompt["id"][:-8] + "00000000"
    assert client.get(_url(f"events/{stale}")).status_code == 409
    assert client.get(_url("events/not-an-id")).status_code == 422

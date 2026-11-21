
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core.timeline.identity import ConversationIndex
from tests.python.timeline.exposure_helpers import (
    CONV, SESSION, append, assistant, build_index, call, result, turn, user,
)

KEY = "ghp_" + "a1B2c3D4" * 5
ROW_ID = 7


def _url(path: str, session: str = "ses_1") -> str:
    return f"/api/v1/sessions/{session}/timeline/{path}"



class _Manager:

    def __init__(self) -> None:
        self.calls = 0

    async def list_session_infos(self) -> List[Any]:
        self.calls += 1
        return []


class _Publisher:

    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self.rows, self.calls = rows, 0

    async def snapshot(self, max_age: Any = None) -> Dict[str, Any]:
        self.calls += 1
        return {"stream": "s", "seq": 1, "collections": {"list": {"rows": self.rows, "ok": True}}}


def _live_row(**over: Any) -> Dict[str, Any]:
    return {"session": {"id": "ses_1"}, "tmux_session": "cloude_x", "session_row_id": ROW_ID, "host_key": "local",
            "activity_status": "working", "status_source": "transcript", "unread": False, "startup_gate": None, **over}


@pytest.fixture
def live(tmp_path: Path, switch, monkeypatch: pytest.MonkeyPatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.timeline import routes as timeline_routes
    from src.api.auth import require_auth
    from src.core.bookmarks import rows
    from src.core.bookmarks.errors import SessionNotFound
    from src.core.session_timeline import gather
    from src.core.timeline import files, service

    main = tmp_path / "proj" / f"{CONV}.jsonl"
    row = SimpleNamespace(id=ROW_ID, session_uuid=SESSION, claude_session_uuid=CONV, working_dir=str(tmp_path), agent_type="claude",
                          host_key="local")

    def read_row(key: str, path: Any = None) -> Any:
        if key in (SESSION, str(ROW_ID)):
            return row
        raise SessionNotFound("no session with that id")

    monkeypatch.setattr(rows, "read_row", read_row)
    monkeypatch.setattr(rows, "family_of", lambda agent: "claude")
    monkeypatch.setattr(files, "main_file", lambda conv, cwd: str(main.resolve()))
    monkeypatch.setattr(service, "_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(gather, "conversations_of", lambda key: (row, [CONV]))
    manager, publisher = _Manager(), _Publisher([_live_row()])
    app = FastAPI()
    app.include_router(timeline_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager, app.state.listing_publisher = manager, publisher
    append(main, turn(0, "a"))
    return TestClient(app), main, manager, publisher, row


def test_finding2_resolving_by_session_uuid_shows_the_lights_of_a_live_session(live) -> None:
    client, _main, manager, publisher, _row = live
    answer = client.get(_url("state", SESSION)).json()
    assert answer["live"] == {"status": "working", "status_source": "transcript", "unread": False, "startup_gate": None}
    assert manager.calls == 0 and publisher.calls == 1
    publisher.rows = []
    assert client.get(_url("state", SESSION)).json()["live"] is None


def test_lowa_a_live_id_resolves_through_the_pushed_listing_and_never_builds_a_listing_pass(live) -> None:
    client, _main, manager, _publisher, _row = live
    assert client.get(_url("state", "ses_1")).status_code == 200
    assert client.get(_url("state", "cloude_x")).status_code == 200
    assert manager.calls == 0


@pytest.mark.parametrize("key", [SESSION, str(ROW_ID)])
def test_lowa_a_paired_computers_row_answers_404(live, key: str) -> None:
    client, _main, _manager, _publisher, row = live
    row.host_key = "peer-b"
    answer = client.get(_url("state", key))
    assert answer.status_code == 404, answer.text



def test_finding3_a_half_indexed_conversation_answers_the_newest_window_and_says_indexing(api, tmp_path: Path) -> None:
    client, main = api
    for index in range(3):
        append(main, turn(10 * index, str(index)))
    one_turn = len(main.read_bytes()) // 3
    build_index(tmp_path / "state", main, upto=one_turn)
    newest = client.get(_url("events")).json()
    assert newest["indexing"]["pct"] == 33
    kinds = [e["kind"] for e in newest["events"]]
    assert newest["events"][-1]["pos"]["offset"] == main.stat().st_size
    assert kinds.count("prompt") == 3
    older = client.get(_url("events"), params={"before_turn": 1 << 40}).json()
    assert older["events"] and older["events"][-1]["pos"]["offset"] <= one_turn



def test_finding5_backward_paging_at_limit_300_reaches_every_turn_exactly_once(api, tmp_path: Path) -> None:
    client, main = api
    for index in range(250):
        append(main, turn(10 * index, str(index)))
    build_index(tmp_path / "state", main)
    seen: List[int] = []
    before = None
    for _page in range(6):
        params: Dict[str, Any] = {"limit": 300, "level": 1}
        if before is not None:
            params["before_turn"] = before
        page = client.get(_url("events"), params=params).json()
        seen = sorted({e["turn"] for e in page["events"]}) + seen
        before = page["next_before"]
        if before is None:
            break
    assert len(seen) == len(set(seen)) == 250


def test_finding5_the_turns_list_at_limit_200_pages_to_every_turn(api, tmp_path: Path) -> None:
    client, main = api
    for index in range(250):
        append(main, turn(10 * index, str(index)))
    build_index(tmp_path / "state", main)
    seen: List[int] = []
    before = None
    for _page in range(6):
        params: Dict[str, Any] = {"limit": 200}
        if before is not None:
            params["before"] = before
        page = client.get(_url("turns"), params=params).json()
        seen.extend(t["turn"] for t in page["turns"])
        before = page["next_before"]
        if before is None:
            break
    assert len(seen) == len(set(seen)) == 250



def _sessions_db(path: Path, rows: List[tuple]) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_uuid TEXT, claude_session_uuid TEXT, lifecycle TEXT)")
        conn.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?)", rows)
        conn.commit()


def test_finding6_a_conversation_two_rows_claim_belongs_to_the_live_one_else_the_newest(tmp_path: Path) -> None:
    db = tmp_path / "carnivore.db"
    _sessions_db(db, [(1, "old-dead", "conv-1", "stopped"), (2, "new-live", "conv-1", "running"), (3, "newer-dead", "conv-1", "stopped"),
                      (4, "a-dead", "conv-2", "stopped"), (5, "b-dead", "conv-2", "stopped"),
                      (6, "old-live", "conv-3", "running"), (7, "new-live", "conv-3", "running")])
    index = ConversationIndex(lambda: db)
    assert index.session_of("conv-1") == "new-live"
    assert index.session_of("conv-2") == "b-dead"
    assert index.session_of("conv-3") == "new-live"



def test_finding8_a_turn_over_8_mib_answers_prompt_last_reply_and_a_chip_not_its_first_8_mib(api, tmp_path: Path) -> None:
    client, main = api
    big = "y" * (3 * 1024 * 1024)
    records = [user(0, "start the long job"), assistant(1, [call("c1", "Bash")]), result(2, "c1"), assistant(3, [call("c2", "Bash")]),
               result(3, "c2"), assistant(4, [call("c3", "Edit")])]
    for number, record in enumerate(records):
        if record["type"] == "user" and number:
            record["message"]["content"][0]["content"] = big
    records += [result(5, "c3"), assistant(6, [{"type": "text", "text": "all done"}], msg="final", stop="end_turn")]
    records[6]["message"]["content"][0]["content"] = big
    append(main, records)
    append(main, turn(20, "after"))
    build_index(tmp_path / "state", main)
    page = client.get(_url("events"), params={"level": 3, "limit": 5}).json()
    giant = [chip for chip in page["chips"] if chip["giant"]]
    assert len(giant) == 1 and giant[0]["calls"] == 3 and giant[0]["replies"] >= 1 and giant[0]["bytes"] > 8 * 1024 * 1024
    in_giant = [e for e in page["events"] if e["turn"] == giant[0]["turn"]]
    assert [e["kind"] for e in in_giant] == ["prompt", "reply"], [e["kind"] for e in in_giant]
    assert len(json.dumps(page)) < 64 * 1024



def test_lowb_a_credential_straddling_the_cut_of_an_oversize_line_is_starred(api) -> None:
    client, main = api
    cut = 64 * 1024
    probe = json.dumps({"type": "user", "uuid": "u-big", "timestamp": "2026-11-01T10:00:00.000Z",
                        "message": {"role": "user", "content": "@@"}}, separators=(",", ":"))
    lead = cut - 10 - probe.index("@@")
    record = {"type": "user", "uuid": "u-big", "timestamp": "2026-11-01T10:00:00.000Z",
              "message": {"role": "user", "content": "a" * lead + KEY + "b" * (5 * 1024 * 1024 + 100)}}
    append(main, [record])
    listed = client.get(_url("events"), params={"after": f"{CONV}:main:0:"}).json()["events"]
    shown = client.get(_url(f"events/{listed[0]['id']}")).json()
    assert shown["truncated"] is True and len(shown["body"]) == cut
    assert KEY[:8] not in shown["body"], "half a credential was shown"

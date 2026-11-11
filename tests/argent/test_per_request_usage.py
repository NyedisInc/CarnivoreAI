
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.session_token_usage import per_request
from src.core.session_token_usage.reader import SessionSubject
from src.core.stat_gate import dir_names
from src.core.subagents.reader import read_subagents

CONV = "11111111-2222-3333-4444-555555555555"


def _line(request_id, message_id, at, agent="", model="claude-opus-4-5", inp=10, out=20, cw=30, cr=40):
    return json.dumps({
        "type": "assistant", "requestId": request_id, "timestamp": at, "agentId": agent,
        "message": {"id": message_id, "model": model, "usage": {
            "input_tokens": inp, "output_tokens": out,
            "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr}},
    }) + "\n"


@pytest.fixture()
def corpus(tmp_path):
    per_request.clear()
    dir_names.clear()
    project = tmp_path / "projects" / "-w"
    main = project / f"{CONV}.jsonl"
    subs = project / CONV / "subagents"
    wf = subs / "workflows" / "wf_build"
    wf.mkdir(parents=True)
    main.write_text(
        _line("req_m1", "msg_m1", "2026-11-05T10:00:00Z")
        + _line("req_m1", "msg_m1", "2026-11-05T10:00:01Z")
        + _line("req_m2", "msg_m2", "2026-11-05T10:05:00Z", out=99)
        + '{"type": "assistant", "requestId": "req_torn"'
    )
    (subs / "agent-aaaa1111.jsonl").write_text(_line("req_s1", "msg_s1", "2026-11-05T10:01:00Z", "aaaa1111", model="claude-haiku-4-5"))
    (wf / "agent-bbbb2222.jsonl").write_text(_line("req_w1", "msg_w1", "2026-11-05T10:02:00Z", "bbbb2222"))
    (wf / "agent-bbbb2222.meta.json").write_text("{}")
    return tmp_path / "projects", main, wf


def _read(main, **kw):
    rows, total, truncated = per_request.read_conversation_requests(main, **kw)
    return rows, total, truncated


def test_one_row_per_request_with_agent_by_file(corpus):
    _, main, _ = corpus
    rows, total, truncated = _read(main)
    assert [(r.request_id, r.agent_id, r.workflow) for r in rows] == [
        ("req_m1", "", None), ("req_s1", "aaaa1111", None), ("req_w1", "bbbb2222", "wf_build"), ("req_m2", "", None)]
    assert total == 4 and truncated is False
    assert rows[1].model == "claude-haiku-4-5"
    first = rows[0].model_dump()
    assert (first["input_tokens"], first["output_tokens"], first["cache_creation_tokens"], first["cache_read_tokens"]) == (10, 20, 30, 40)
    assert not [k for k in first if "cost" in k or "usd" in k or "dollar" in k]


def test_negative_control_a_naive_per_line_count_would_differ(corpus):
    _, main, wf = corpus
    naive = sum(p.read_text().count('"usage"') for p in [main, *wf.parent.parent.glob("agent-*.jsonl"), *wf.glob("agent-*.jsonl")])
    assert naive == 5 and _read(main)[1] == 4
    assert "req_w1" in [r.request_id for r in _read(main)[0]]


def test_cursor_reads_only_the_new_tail_and_a_rewrite_rescans(corpus):
    _, main, _ = corpus
    _read(main)
    with open(main, "a") as handle:
        handle.write(', "message": {"id": "msg_torn", "usage": {"input_tokens": 1}}}\n')
        handle.write(_line("req_m3", "msg_m3", "2026-11-05T10:09:00Z"))
    rows, total, _ = _read(main)
    assert [r.request_id for r in rows].count("req_m3") == 1 and total == 6
    state = per_request._states[str(main)]
    assert state.offset == main.stat().st_size
    main.write_text(_line("req_new", "msg_new", "2026-11-05T11:00:00Z"))
    rows, _, _ = _read(main)
    assert [r.request_id for r in rows if r.agent_id == ""] == ["req_new"]


def test_since_is_exclusive_and_limit_truncates_with_a_continuation(corpus):
    _, main, _ = corpus
    rows, total, _ = _read(main, since="2026-11-05T10:01:00Z")
    assert [r.request_id for r in rows] == ["req_w1", "req_m2"] and total == 2
    page, total, truncated = _read(main, limit=1)
    assert [r.request_id for r in page] == ["req_m1"] and total == 4 and truncated
    nxt, _, _ = _read(main, since=page[-1].timestamp, limit=1)
    assert [r.request_id for r in nxt] == ["req_s1"]
    with pytest.raises(ValueError):
        _read(main, since="not a time")
    with pytest.raises(ValueError):
        _read(main, limit=0)


def test_session_dispatch_states(corpus):
    projects, _, _ = corpus
    assert per_request.read_session_requests(SessionSubject("codex", "x", "/w"), projects_dir=projects).state == "not_applicable"
    assert per_request.read_session_requests(SessionSubject("claude", None, "/w"), projects_dir=projects).state == "absent"
    ok = per_request.read_session_requests(SessionSubject("claude", CONV, "/w"), projects_dir=projects)
    assert ok.state == "ok" and ok.total == 4
    assert per_request.read_session_requests(SessionSubject("claude", "00000000-0000-0000-0000-000000000000", "/w"),
                                             projects_dir=projects).state == "absent"


def test_workflow_agents_are_listed_with_the_subagents(corpus):
    _, main, wf = corpus
    ids = {s.id for s in read_subagents(main, conversation_uuid=CONV).subagents}
    assert ids == {"aaaa1111", "bbbb2222"}
    (wf.parent.parent / "agent-cccc3333.meta.json").write_text("{}")
    assert read_subagents(main, conversation_uuid=CONV).counts.total == 3

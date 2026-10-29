from __future__ import annotations

import json
from pathlib import Path

from src.core.stats import StatsStore, events
from tests.stats import seed

CANARIES = ("CANARY_PROMPT_9f1", "CANARY_REPLY_9f2", "CANARY_TOOLIN_9f3", "CANARY_TOOLOUT_9f4",
            "CANARY_BRANCH_9f5", "CANARY_SIDECAR_9f6", "CANARY_NICK_9f7", "CANARY_INSTR_9f8",
            "CANARY_RULES_9f9", "CANARY_CWD_9fa", "CANARY_THINK_9fb", "CANARY_ARGS_9fc",
            "CANARY_COMPACT_9fd", "CANARY_WEBQ_9fe")
PARENT = "33333333-3333-4333-8333-333333333333"
CODEX = "019a0000-0000-7000-8000-00000000abcd"


def _dump(store: StatsStore) -> str:
    parts = []
    with store.connect(readonly=True) as db:
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            for row in db.execute(f'SELECT * FROM "{name}"'):
                parts.append(name + ":" + "|".join(map(str, tuple(row))))
    for suffix in ("", "-wal"):
        path = Path(str(store.db_path) + suffix)
        if path.exists():
            parts.append(path.read_bytes().decode("latin-1"))
    return "\n".join(parts)


def test_no_canary_reaches_the_stats_database(tmp_path):
    claude = tmp_path / "claude"
    (claude / "proj" / PARENT / "subagents").mkdir(parents=True)
    lines = [
        {"type": "user", "timestamp": "2026-09-28T12:00:00Z", "cwd": "/tmp/CANARY_CWD_9fa", "version": "2.1.9",
         "gitBranch": "CANARY_BRANCH_9f5", "message": {"role": "user", "content": "CANARY_PROMPT_9f1"}},
        {"type": "assistant", "timestamp": "2026-09-28T12:01:00Z", "cwd": "/tmp/CANARY_CWD_9fa",
         "version": "2.1.9", "gitBranch": "CANARY_BRANCH_9f5",
         "message": {"id": "m1", "model": "claude-sonnet-4-6",
                     "content": [{"type": "text", "text": "CANARY_REPLY_9f2"},
                                 {"type": "thinking", "thinking": "CANARY_THINK_9fb"},
                                 {"type": "tool_use", "id": "t1", "name": "Bash",
                                  "input": {"command": "echo CANARY_TOOLIN_9f3"}},
                                 {"type": "tool_use", "id": "t2", "name": "CANARY_WEBQ_9fe with spaces",
                                  "input": {"query": "CANARY_WEBQ_9fe"}}],
                     "stop_reason": "tool_use",
                     "usage": {"input_tokens": 10, "output_tokens": 2,
                               "output_tokens_details": {"thinking_tokens": 9},
                               "server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 1},
                               "cache_creation": {"ephemeral_5m_input_tokens": 3,
                                                  "ephemeral_1h_input_tokens": 4}}}},
        {"type": "system", "subtype": "compact_boundary", "uuid": "c1", "timestamp": "2026-09-28T12:01:30Z",
         "cwd": "/tmp/CANARY_CWD_9fa", "content": "CANARY_COMPACT_9fd",
         "compactMetadata": {"trigger": "manual", "preCompactDiscoveredTools": ["CANARY_COMPACT_9fd"]}},
        {"type": "system", "subtype": "turn_duration", "uuid": "c2", "timestamp": "2026-09-28T12:01:40Z",
         "cwd": "/tmp/CANARY_CWD_9fa", "durationMs": 5},
        {"type": "user", "timestamp": "2026-09-28T12:02:00Z", "cwd": "/tmp/CANARY_CWD_9fa",
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                                    "content": "CANARY_TOOLOUT_9f4"}]}},
    ]
    parent = claude / "proj" / f"{PARENT}.jsonl"
    parent.write_text("".join(json.dumps(x) + "\n" for x in lines))
    sub = claude / "proj" / PARENT / "subagents" / "agent-zz.jsonl"
    sub.write_text("".join(json.dumps(x) + "\n" for x in lines))
    sub.with_suffix(".meta.json").write_text(json.dumps(
        {"agentType": "reviewer", "description": "CANARY_SIDECAR_9f6"}))
    (claude / "proj" / "CLAUDE.md").write_text("CANARY_RULES_9f9")

    codex = tmp_path / "codex" / "2026" / "09" / "28"
    codex.mkdir(parents=True)
    (codex / f"rollout-2026-09-28T12-00-00-{CODEX}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in [
        {"type": "session_meta", "timestamp": "2026-09-28T12:00:00Z", "payload": {
            "id": CODEX, "cwd": "/tmp/CANARY_CWD_9fa", "cli_version": "0.154.0", "thread_source": "subagent",
            "agent_role": "validator", "agent_nickname": "CANARY_NICK_9f7", "parent_thread_id": PARENT,
            "base_instructions": {"text": "CANARY_INSTR_9f8"}, "git": {"branch": "CANARY_BRANCH_9f5"}}},
        {"type": "turn_context", "timestamp": "2026-09-28T12:00:01Z", "payload": {"model": "gpt-5"}},
        {"type": "response_item", "timestamp": "2026-09-28T12:00:02Z",
         "payload": {"type": "message", "content": [{"text": "CANARY_REPLY_9f2 CANARY_PROMPT_9f1"}]}},
        {"type": "response_item", "timestamp": "2026-09-28T12:00:02Z", "payload": {
            "type": "function_call", "name": "shell", "call_id": "c1", "arguments": "CANARY_ARGS_9fc"}},
        {"type": "response_item", "timestamp": "2026-09-28T12:00:02Z", "payload": {
            "type": "reasoning", "summary": [{"text": "CANARY_THINK_9fb"}]}},
        {"type": "event_msg", "timestamp": "2026-09-28T12:00:03Z", "payload": {
            "type": "token_count", "info": {"total_token_usage": {
                "input_tokens": 5, "cached_input_tokens": 0, "output_tokens": 3,
                "reasoning_output_tokens": 2}}}},
    ]))

    store = StatsStore(tmp_path / "state")
    store.initialize()
    rollout = codex / f"rollout-2026-09-28T12-00-00-{CODEX}.jsonl"
    seed.deliver(store.state_dir, parent, family="claude", conversation_id=PARENT)
    seed.deliver(store.state_dir, sub, family="claude", conversation_id=PARENT, file_kind="subagent")
    seed.deliver(store.state_dir, rollout, family="codex", conversation_id=CODEX)
    events.record("session_created", "ses_x", {"n": 1}, store=store)

    with store.connect(readonly=True) as db:
        assert db.execute("SELECT COUNT(*) FROM minute_usage").fetchone()[0] >= 2
        rows = db.execute("SELECT conversation_id,subagent_type,branch_hash FROM conversation_meta").fetchall()
    with store.connect(readonly=True) as db:
        counted = {(r[0], r[1]) for r in db.execute("SELECT counter,key FROM minute_counters")}
    assert {("tool_calls", "Bash"), ("tool_calls", "other"), ("tool_calls", "shell"), ("turns", ""),
            ("compactions", "manual"), ("thinking_tokens", ""), ("web_searches", "")} <= counted
    assert {r["subagent_type"] for r in rows} >= {"reviewer", "validator"}
    assert all(r["branch_hash"] and len(r["branch_hash"]) == 16 for r in rows)
    dump = _dump(store)
    assert "reviewer" in dump
    for canary in CANARIES:
        assert canary not in dump, canary

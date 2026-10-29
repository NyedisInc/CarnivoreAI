
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BASE = datetime(2026, 10, 11, 18, 30, 0, tzinfo=timezone.utc).timestamp()
B, F, D, M = ("b0000000-0000-4000-8000-00000000000b", "f0000000-0000-4000-8000-00000000000f",
              "d0000000-0000-4000-8000-00000000000d", "e0000000-0000-4000-8000-00000000000e")
CONV = {B: "conv-briefing", F: "conv-harbor", D: "conv-docker", M: "conv-monitoring"}
APP = {B: "ses_bbbbbbbb", F: "ses_ffffffff", D: "ses_dddddddd", M: "ses_eeeeeeee"}
AGENT_ID = "a1e531fcc1deac32e"
SPAWN_AT = BASE - 7 * 3600


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def rec(kind: str, t: float, **fields: Any) -> Dict[str, Any]:
    return {"type": kind, "timestamp": iso(t), "uuid": f"u-{kind}-{int(t * 1000)}", **fields}


def user(t: float, content: Any, **fields: Any) -> Dict[str, Any]:
    return rec("user", t, message={"role": "user", "content": content}, **fields)


def call(t: float, tool_id: str, name: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return rec("assistant", t, message={"role": "assistant", "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": args or {}}]})


def result(t: float, tool_id: str, text: str) -> Dict[str, Any]:
    return user(t, [{"type": "tool_result", "tool_use_id": tool_id, "content": text}])


def envelope(thread: str, msg: str) -> str:
    return f"Another Claude session sent a message:\n<cross-session-message>\ncrosstalk from @X (claude) thread {thread} msg {msg}\nbody"


def write_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def transcripts(root: Path) -> Dict[str, Path]:
    paths = {u: root / f"{c}.jsonl" for u, c in CONV.items()}
    write_jsonl(paths[B], [
        user(BASE + 250, "<channel list=8>", promptId="p-b1", turnOrigin="peer", origin={"kind": "channel", "server": "carnivore"}),
        call(BASE + 253, "tb1", "mcp__carnivore__huddle_batch"),
        result(BASE + 253.2, "tb1", json.dumps({"results": [{"message_id": 1914, "item_id": 395}]})),
        call(BASE + 255, "tb2", "mcp__carnivore__crosstalk_send"),
        result(BASE + 255.1, "tb2", json.dumps({"id": "m-N8jp", "thread": "t-qA4j", "status": "queued", "to": APP[F]})),
        rec("system", BASE + 258, subtype="turn_duration", durationMs=8000),
        user(BASE + 259, envelope("t-qA4j", "m-xGDy"), promptId="p-b2", turnOrigin="peer", origin={"kind": "peer"}),
        call(BASE + 3400.9, "tb3", "mcp__carnivore__huddle_update", {"item_id": 395}),
        result(BASE + 3401.0, "tb3", json.dumps({"item_id": 395})),
        rec("system", BASE + 3402, subtype="turn_duration", durationMs=2000),
    ])
    sub_dir = paths[F].with_suffix("") / "subagents"
    write_jsonl(paths[F], [
        user(BASE + 255.3, envelope("t-qA4j", "m-N8jp"), promptId="p-f1", turnOrigin="peer", origin={"kind": "peer"}),
        call(BASE + 270, "tf1", "mcp__carnivore__huddle_add"),
        result(BASE + 270.5, "tf1", json.dumps({"item_id": 408})),
        call(BASE + 290, "tf2", "Agent", {"description": "Fix NAS path", "subagent_type": "worker"}),
        result(BASE + 290.01, "tf2", f"Async agent launched\nagentId: {AGENT_ID}"),
        call(BASE + 292, "tf3", "mcp__carnivore__crosstalk_reply"),
        result(BASE + 292.2, "tf3", json.dumps({"id": "m-xGDy", "thread": "t-qA4j", "status": "queued", "to": APP[B]})),
        rec("system", BASE + 295, subtype="turn_duration", durationMs=40000),
        user(BASE + 3000, f"<task-notification>\n<task-id>{AGENT_ID}</task-id>\n<tool-use-id>tf2</tool-use-id>\n<status>completed</status>\n</task-notification>",
             promptId="p-f2", turnOrigin="task_notification", origin={"kind": "task-notification"}),
        call(BASE + 3010, "tf4", "mcp__carnivore__crosstalk_send"),
        result(BASE + 3010.2, "tf4", json.dumps({"id": "m-6LGV", "thread": "t-15FU", "status": "queued", "to": APP[D]})),
        rec("system", BASE + 3012, subtype="turn_duration", durationMs=12000),
    ])
    write_jsonl(sub_dir / f"agent-{AGENT_ID}.jsonl", [
        user(BASE + 290.1, "do the thing", promptId="p-f1", isSidechain=True, agentId=AGENT_ID),
        call(BASE + 300, "ts1", "Bash"), result(BASE + 360, "ts1", "ok"),
        call(BASE + 361, "ts2", "Write"), result(BASE + 361.5, "ts2", "ok"),
        rec("assistant", BASE + 2990, isSidechain=True, agentId=AGENT_ID, message={"content": [{"type": "text", "text": "done"}]}),
    ])
    (sub_dir / f"agent-{AGENT_ID}.meta.json").write_text(json.dumps({"agentType": "worker", "description": "Fix nightly_backup path", "toolUseId": "tf2"}))
    write_jsonl(paths[D], [user(BASE + 3010.5, envelope("t-15FU", "m-6LGV"), promptId="p-d1", turnOrigin="peer", origin={"kind": "peer"}),
                           rec("system", BASE + 3040, subtype="turn_duration", durationMs=30000)])
    write_jsonl(paths[M], [user(BASE - 5, "unrelated", promptId="p-m1")])
    return paths


CORE_SCHEMA = """
CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_uuid TEXT UNIQUE, claude_session_uuid TEXT, tmux_name TEXT, title TEXT,
  working_dir TEXT, project_id INTEGER, origin TEXT, agent_family TEXT, created_at TEXT);
CREATE TABLE conversation_index (conversation_id TEXT UNIQUE, agent_family TEXT, session_uuid TEXT, started_at TEXT, ended_at TEXT);
CREATE TABLE crosstalk_messages (id TEXT PRIMARY KEY, thread TEXT, sender_id TEXT, receiver_id TEXT, sender_uuid TEXT, receiver_uuid TEXT,
  sender_name TEXT, receiver_name TEXT, text TEXT, in_reply_to TEXT, expect_reply INTEGER, status TEXT, created_at REAL, delivered_at REAL, source TEXT);
CREATE TABLE crosstalk_contacts (pair_key TEXT PRIMARY KEY, left_key TEXT, right_key TEXT, granted_at REAL, source TEXT);
CREATE TABLE lineage_edges (parent_type TEXT, parent_id TEXT, child_type TEXT, child_id TEXT, edge_kind TEXT, link_basis TEXT, detail_json TEXT, created_at TEXT);
"""
TASK_MANAGER_SCHEMA = """
CREATE TABLE work_items (id INTEGER PRIMARY KEY, list_key TEXT, text TEXT, created_by TEXT, state TEXT, created_at REAL, updated_at REAL, deleted INTEGER DEFAULT 0);
CREATE TABLE work_messages (id INTEGER PRIMARY KEY, item_id INTEGER, author TEXT, author_key TEXT, kind TEXT, text TEXT, created_at REAL, seq INTEGER);
CREATE TABLE work_card_events (id INTEGER PRIMARY KEY, item_id INTEGER, list_key TEXT, at REAL, kind TEXT, from_col TEXT, to_col TEXT, by TEXT, detail TEXT DEFAULT '');
"""


def make_install(tmp: Path) -> Dict[str, Any]:
    state = tmp / "state"
    (state / "cplugs" / "huddle").mkdir(parents=True)
    paths = transcripts(tmp / "transcripts")
    core = sqlite3.connect(state / "carnivore.db")
    core.executescript(CORE_SCHEMA)
    for n, (u, name) in enumerate({B: "Daily Bulletin", F: "Harbor", D: "Harbor Docker", M: "Harbor Monitoring"}.items(), 1):
        core.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?)", (n, u, CONV[u], f"carnivore_{n}", name, "/w", 1, "created", "claude", iso(SPAWN_AT)))
        core.execute("INSERT INTO conversation_index VALUES (?,?,?,?,?)", (CONV[u], "claude", u, iso(SPAWN_AT), None))
    rows = [("m-N8jp", "t-qA4j", B, F, "briefing asks harbor", None, BASE + 255.1, BASE + 255.3),
            ("m-xGDy", "t-qA4j", F, B, "harbor answers", "m-N8jp", BASE + 292.2, BASE + 292.5),
            ("m-6LGV", "t-15FU", F, D, "harbor hands docker a task", None, BASE + 3010.2, BASE + 3010.5),
            ("m-OLD0", "t-old0", F, M, "spawn task to the other child", None, SPAWN_AT + 0.5, SPAWN_AT + 1),
            ("m-OLD1", "t-old", F, D, "spawn task from the night before", None, SPAWN_AT + 1, SPAWN_AT + 2)]
    for mid, thread, s, r, text, reply, created, delivered in rows:
        core.execute("INSERT INTO crosstalk_messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (mid, thread, APP[s], APP[r], s, r, "s", "r", text, reply, 1, "delivered", created, delivered, "crosstalk"))
    core.execute("INSERT INTO crosstalk_contacts VALUES (?,?,?,?,?)", (f"{M}|{F}", M, F, SPAWN_AT - 4, "spawn|o=0"))
    core.execute("INSERT INTO crosstalk_contacts VALUES (?,?,?,?,?)", (f"{D}|{F}", D, F, SPAWN_AT, "spawn|o=0"))
    core.commit()
    core.close()
    hud = sqlite3.connect(state / "carnivore.db")
    hud.executescript(TASK_MANAGER_SCHEMA)
    hud.execute("INSERT INTO work_items VALUES (395,'8','fix the nightly job path',?,'review',?,?,0)", (B, BASE - 6 * 3600, BASE + 3400))
    hud.execute("INSERT INTO work_items VALUES (408,'13','harbor copy',?,'review',?,?,0)", (F, BASE + 270.4, BASE + 3000))
    hud.execute("INSERT INTO work_messages VALUES (1913,395,'joe','owner','reply','do it',?,1)", (BASE + 249.9,))
    hud.execute("INSERT INTO work_messages VALUES (1914,395,'claude',?,'info','briefing note',?,2)", (B, BASE + 253.2))
    hud.execute("INSERT INTO work_card_events VALUES (1,395,'8',?,'created','','todo',?,'')", (BASE - 6 * 3600, B))
    hud.execute("INSERT INTO work_card_events VALUES (2,395,'8',?,'moved','in_progress','review','claude','')", (BASE + 3401.05,))
    hud.commit()
    hud.close()
    return {"state_dir": state, "paths": paths}

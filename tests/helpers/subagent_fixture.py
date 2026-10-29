
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

CONV = "5ab0c0de-0000-4000-8000-00000000c0de"
PROJECT_DIR = "-tmp-fixture-project"
WORKDIR = "/tmp/fixture-project"
VERSION = "2.1.283"
A, B, C, D, E, F, G, H, I = (
    "a1000000000000001", "a2000000000000002", "a3000000000000003",
    "a4000000000000004", "a5000000000000005", "a6000000000000006",
    "a7000000000000007", "a8000000000000008", "a9000000000000009",
)


def ts(hour: int, minute: int, second: int = 0) -> str:
    return f"2026-09-26T{hour:02d}:{minute:02d}:{second:02d}.000Z"


def _envelope(agent: str, kind: str, at: str, **extra: Any) -> Dict[str, Any]:
    record = {
        "parentUuid": None, "isSidechain": True, "agentId": agent, "type": kind,
        "uuid": f"u-{agent}-{at}", "timestamp": at, "userType": "external",
        "entrypoint": "cli", "cwd": WORKDIR, "sessionId": CONV, "version": VERSION,
        "gitBranch": "main", "slug": "fixture-slug",
    }
    record.update(extra)
    return record


def assistant(agent: str, at: str, stop: Optional[str] = "end_turn", tool: bool = False) -> Dict[str, Any]:
    block = ({"type": "tool_use", "id": f"toolu_inner_{agent}", "name": "Bash", "input": {}}
             if tool else {"type": "text", "text": "placeholder"})
    return _envelope(agent, "assistant", at, requestId="req_placeholder", apiBlockIndex=0,
                     attributionAgent="general-purpose", effort="high",
                     message={"id": "msg_placeholder", "type": "message", "role": "assistant",
                              "model": "claude-fixture", "content": [block],
                              "stop_reason": stop,
                              "usage": {"input_tokens": 1, "output_tokens": 1}})


def user(agent: str, at: str, text: str = "placeholder task prompt") -> Dict[str, Any]:
    return _envelope(agent, "user", at, promptId="prompt-placeholder",
                     message={"role": "user", "content": text})


def tool_result(agent: str, at: str, tool_use_id: str) -> Dict[str, Any]:
    return _envelope(agent, "user", at, promptId="prompt-placeholder",
                     message={"role": "user", "content": [
                         {"tool_use_id": tool_use_id, "type": "tool_result",
                          "content": "placeholder result"}]})


def injected(agent: str, at: str) -> Dict[str, Any]:
    return _envelope(agent, "user", at, promptId="prompt-placeholder", isMeta=True,
                     origin={"kind": "task-notification"},
                     message={"role": "user",
                              "content": "[SYSTEM NOTIFICATION - NOT USER INPUT]\nplaceholder"})


def attachment(agent: str, at: str) -> Dict[str, Any]:
    return _envelope(agent, "attachment", at,
                     attachment={"type": "deferred_tools_record", "entries": []})


def notification(ids: Iterable[str], status: str) -> str:
    body = "".join(f"<task-id>{task}</task-id>\n" for task in ids)
    return ("<task-notification>\n" + body + "<tool-use-id>toolu_x</tool-use-id>\n"
            "<output-file>/placeholder</output-file>\n"
            f"<status>{status}</status>\n<summary>placeholder</summary>\n"
            "<note>placeholder</note>\n</task-notification>")


def _parent(kind: str, at: str, **extra: Any) -> Dict[str, Any]:
    record = {"parentUuid": None, "isSidechain": False, "type": kind, "uuid": f"p-{at}",
              "timestamp": at, "userType": "external", "entrypoint": "cli", "cwd": WORKDIR,
              "sessionId": CONV, "version": VERSION, "gitBranch": "main"}
    record.update(extra)
    return record


def launch(at: str, tool_use_id: str, agent: str, status: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"status": status, "agentId": agent, "prompt": "placeholder"}
    if status == "async_launched":
        result.update({"isAsync": True, "description": "placeholder",
                       "outputFile": "/placeholder", "canReadOutputFile": True})
        text = f"Async agent launched successfully.\nagentId: {agent} (placeholder)"
    else:
        result.update({"agentType": "general-purpose", "content": [], "totalDurationMs": 1})
        text = "placeholder result"
    return _parent("user", at, promptId="p", toolUseResult=result,
                   message={"role": "user", "content": [
                       {"tool_use_id": tool_use_id, "type": "tool_result",
                        "content": [{"type": "text", "text": text}]}]})


def _write_lines(path: Path, lines: List[Dict[str, Any]], torn: str = "") -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")
        handle.write(torn)


def build_corpus(root: Path) -> Path:
    project = root / PROJECT_DIR
    sub = project / CONV / "subagents"
    sub.mkdir(parents=True)

    def agent(agent_id: str, meta: Dict[str, Any], lines: List[Dict[str, Any]], torn: str = "") -> None:
        (sub / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta))
        _write_lines(sub / f"agent-{agent_id}.jsonl", lines, torn)

    agent(A, {"agentType": "general-purpose", "description": "fixture foreground",
              "model": "claude-fixture", "spawnDepth": 1, "toolUseId": "toolu_A"},
          [user(A, ts(10, 0)), assistant(A, ts(10, 4))])
    agent(B, {"agentType": "worker", "description": "fixture background", "model": "claude-fixture",
              "requestShape": "background", "requestNonInteractive": True, "spawnDepth": 1,
              "toolUseId": "toolu_B"},
          [user(B, ts(10, 10)), assistant(B, ts(11, 20), stop="tool_use", tool=True),
           tool_result(B, ts(11, 30, 5), "toolu_D"), assistant(B, ts(11, 58), stop=None)])
    agent(C, {"agentType": "worker", "description": "fixture queued end",
              "requestShape": "background", "requestNonInteractive": True, "spawnDepth": 1,
              "toolUseId": "toolu_C"},
          [user(C, ts(10, 20)), assistant(C, ts(10, 29)), injected(C, ts(11, 0)),
           attachment(C, ts(11, 0, 1))])
    agent(D, {"agentType": "Explore", "description": "fixture nested", "model": "claude-fixture",
              "parentAgentId": B, "spawnDepth": 2, "toolUseId": "toolu_D"},
          [user(D, ts(11, 21)), assistant(D, ts(11, 30))])
    agent(E, {"agentType": "worker", "description": "fixture silent", "spawnDepth": 1,
              "toolUseId": "toolu_E"},
          [user(E, ts(8, 50)), assistant(E, ts(9, 0), stop="tool_use", tool=True)])
    agent(F, {"agentType": "worker", "description": "fixture resumed", "requestShape": "background",
              "requestNonInteractive": True, "spawnDepth": 1, "toolUseId": "toolu_F"},
          [user(F, ts(10, 30)), assistant(F, ts(10, 39)), user(F, ts(11, 50), "placeholder follow-up"),
           assistant(F, ts(11, 55), stop="tool_use", tool=True)])
    agent(G, {"agentType": 7, "description": "fixture bad meta", "toolUseId": "toolu_G"},
          [user(G, ts(11, 38)), assistant(G, ts(11, 39))])
    broken = assistant(H, ts(11, 50))
    del broken["sessionId"]
    agent(H, {"agentType": "worker", "description": "fixture bad line", "toolUseId": "toolu_H"},
          [user(H, ts(11, 49)), broken])
    agent(I, {"agentType": "worker", "description": "fixture torn", "toolUseId": "toolu_I"},
          [user(I, ts(11, 50)), assistant(I, ts(11, 52))],
          torn='{"parentUuid":null,"isSidechain":tr')
    _write_lines(sub / "agent-acompact-0123abcd.jsonl", [user("acompact-0123abcd", ts(9, 0))])

    parent = [
        _parent("user", ts(9, 59), promptId="p", message={"role": "user", "content": "placeholder"}),
        launch(ts(10, 5), "toolu_A", A, "completed"),
        launch(ts(10, 10, 1), "toolu_B", B, "async_launched"),
        launch(ts(10, 20, 1), "toolu_C", C, "async_launched"),
        _parent("queue-operation", ts(10, 29, 1), operation="enqueue",
                content=notification([C], "completed")),
        _parent("queue-operation", ts(10, 29, 2), operation="remove",
                content=notification([C], "completed")),
        launch(ts(10, 30, 1), "toolu_F", F, "async_launched"),
        _parent("user", ts(10, 39, 1), promptId="p", origin={"kind": "task-notification"},
                message={"role": "user", "content": notification([F], "completed")}),
        _parent("assistant", ts(10, 45), requestId="r",
                message={"role": "assistant", "model": "claude-fixture", "stop_reason": "end_turn",
                         "content": [{"type": "text", "text": notification([E], "completed")}]}),
        launch(ts(11, 40, 1), "toolu_G", G, "completed"),
    ]
    transcript = project / f"{CONV}.jsonl"
    _write_lines(transcript, parent)
    return transcript

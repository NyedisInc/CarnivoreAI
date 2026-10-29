
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

_TS_RE = re.compile(r'"timestamp"\s*:\s*"([^"]+)"')
ENVELOPE_RE = re.compile(r"thread (t-[\w-]+) msg (m-[\w-]+)")
_AGENT_ID_RE = re.compile(r"agentId:\s*([0-9a-f]{8,40})")
_TASK_RE = re.compile(r"<task-id>([^<]+)</task-id>\s*<tool-use-id>([^<]*)</tool-use-id>.*?<status>([^<]*)</status>", re.S)
_MESSAGE_ID_RE = re.compile(r'"message_id"\s*:\s*(\d+)')
_ITEM_ID_RE = re.compile(r'"item_id"\s*:\s*(\d+)')
AGENT_TOOLS = frozenset({"Agent", "Task"})
CROSSTALK_TOOLS = frozenset({"crosstalk_send", "crosstalk_reply"})
TASK_MANAGER_TOOLS = frozenset({"huddle_add", "huddle_reply", "huddle_batch", "huddle_ask", "huddle_update", "huddle_move",
                          "huddle_artifact",
                          "task_manager_add", "task_manager_reply", "task_manager_batch_run", "task_manager_ask",
                          "task_manager_update", "task_manager_move", "task_manager_artifact_add"})
LONG_TOOL_S = 20.0
RESULT_KEEP = 4000
SAY_KEEP = 1200


@dataclass
class Scan:

    conversation_id: str = ""
    path: str = ""
    turns: List[Dict[str, Any]] = field(default_factory=list)
    spans: List[Dict[str, Any]] = field(default_factory=list)
    receipts: List[Dict[str, Any]] = field(default_factory=list)
    launches: List[Dict[str, Any]] = field(default_factory=list)
    returns: List[Dict[str, Any]] = field(default_factory=list)
    sends: List[Dict[str, Any]] = field(default_factory=list)
    spawns: List[Dict[str, Any]] = field(default_factory=list)
    task_manager: List[Dict[str, Any]] = field(default_factory=list)
    says: List[Dict[str, Any]] = field(default_factory=list)
    first_t: Optional[float] = None
    last_t: Optional[float] = None
    records: int = 0


def parse_ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def stamp_of(line: str) -> Optional[float]:
    found = _TS_RE.search(line)
    if not found:
        return None
    try:
        return parse_ts(found.group(1))
    except ValueError:
        return None


def iter_records(path: Path, lo: float, hi: float) -> Iterator[Tuple[int, Dict[str, Any]]]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            stamp = stamp_of(line)
            if stamp is None or stamp < lo or stamp > hi:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield number, record


def _content(record: Dict[str, Any]) -> Any:
    message = record.get("message")
    return message.get("content") if isinstance(message, dict) else None


def _text_of(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(b.get("text", "")) for b in value if isinstance(b, dict) and b.get("type") == "text")
    return ""


def short_tool(name: str) -> str:
    return name.split("__", 2)[-1] if name.startswith("mcp__") else name


def _turn_label(origin: str, text: str) -> str:
    first = ENVELOPE_RE.search(text)
    if first:
        head = text[:first.start()].strip().splitlines()[-1] if text[:first.start()].strip() else ""
        return (head or "peer message")[:80]
    return {"channel": "huddle change", "task_notification": "subagent returned", "human": "prompt"}.get(origin, origin)[:80]


def _origin(record: Dict[str, Any]) -> str:
    turn = record.get("turnOrigin")
    kind = (record.get("origin") or {}).get("kind") if isinstance(record.get("origin"), dict) else None
    if kind == "channel":
        return "channel"
    if turn == "task_notification" or kind == "task-notification":
        return "task_notification"
    if turn == "peer" or kind == "peer":
        return "peer"
    return "human"


def scan_records(records: Iterable[Tuple[int, Dict[str, Any]]], conversation_id: str = "") -> Scan:
    fold = Fold(conversation_id)
    for line, record in records:
        fold.add(line, record)
    return fold.scan


class Fold:

    def __init__(self, conversation_id: str = "") -> None:
        self.scan = Scan(conversation_id=conversation_id)
        self.calls: Dict[str, Dict[str, Any]] = {}
        self.turn: Optional[Dict[str, Any]] = None

    def add(self, line: int, record: Dict[str, Any]) -> None:
        scan = self.scan
        scan.records += 1
        try:
            t = parse_ts(str(record.get("timestamp")))
        except ValueError:
            return
        scan.first_t = t if scan.first_t is None else scan.first_t
        scan.last_t = t
        kind, content, uuid = record.get("type"), _content(record), record.get("uuid")
        if kind == "system" and record.get("subtype") == "turn_duration":
            if self.turn is not None:
                self.turn.update(end=t, duration_s=(record.get("durationMs") or 0) / 1000.0, line_to=line)
                self.turn = None
            return
        if kind == "user":
            self._user(line, record, t, content, uuid)
        elif kind == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    self.calls[str(block.get("id"))] = {"id": block.get("id"), "name": str(block.get("name")),
                                                        "input": block.get("input") or {}, "t": t, "line": line, "uuid": uuid}
                elif block.get("type") == "text" and str(block.get("text") or "").strip():
                    scan.says.append({"t": t, "line": line, "uuid": uuid, "role": "agent", "text": str(block["text"]).strip()[:SAY_KEEP]})
        if self.turn is not None:
            self.turn["end"], self.turn["line_to"] = t, line

    def _user(self, line: int, record: Dict[str, Any], t: float, content: Any, uuid: Any) -> None:
        scan = self.scan
        results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"] if isinstance(content, list) else []
        if results:
            for block in results:
                call = self.calls.pop(str(block.get("tool_use_id")), None)
                if call is not None:
                    _finish_call(scan, call, t, line, _text_of(block.get("content"))[:RESULT_KEEP])
            return
        text = _text_of(content)
        origin = _origin(record)
        self.turn = {"prompt_id": record.get("promptId"), "origin": origin, "start": t, "end": t, "line_from": line,
                     "line_to": line, "uuid": uuid, "label": _turn_label(origin, text), "tools": {}}
        scan.turns.append(self.turn)
        envelope = ENVELOPE_RE.search(text[:600])
        if envelope:
            scan.receipts.append({"thread": envelope.group(1), "msg_id": envelope.group(2), "t": t, "line": line, "uuid": uuid,
                                  "via": "peer" if origin == "peer" else "paste"})
        note = _TASK_RE.search(text)
        if note:
            scan.returns.append({"agent_id": note.group(1), "tool_use_id": note.group(2), "status": note.group(3),
                                 "t": t, "line": line, "uuid": uuid})
        if origin == "human" and not envelope and not note and not record.get("isMeta") and text.strip():
            scan.says.append({"t": t, "line": line, "uuid": uuid, "role": "prompt", "text": text.strip()[:SAY_KEEP]})


def _finish_call(scan: Scan, call: Dict[str, Any], t: float, line: int, result: str) -> None:
    name = short_tool(call["name"])
    span = {"tool_use_id": call["id"], "tool": name, "start": call["t"], "end": t, "line_from": call["line"], "line_to": line,
            "uuid": call["uuid"]}
    scan.spans.append(span)
    for turn in reversed(scan.turns):
        if turn["line_from"] <= call["line"]:
            turn["tools"][name] = turn["tools"].get(name, 0) + 1
            break
    base = {"tool_use_id": call["id"], "t": call["t"], "t_result": t, "line": call["line"], "uuid": call["uuid"]}
    if call["name"] in AGENT_TOOLS:
        found = _AGENT_ID_RE.search(result)
        scan.launches.append({**base, "agent_id": found.group(1) if found else None, "agent_type": call["input"].get("subagent_type"),
                              "description": str(call["input"].get("description") or "")[:120]})
    elif name in CROSSTALK_TOOLS:
        data = _json_object(result)
        if data.get("id"):
            scan.sends.append({**base, "msg_id": data["id"], "thread": data.get("thread"), "to": data.get("to")})
    elif name == "agent_spawn":
        data = _json_object(result)
        if data.get("id"):
            task = data.get("task_message") if isinstance(data.get("task_message"), dict) else {}
            scan.spawns.append({**base, "child_app_id": data["id"], "parent_app_id": data.get("parent"), "task_msg_id": task.get("id")})
    elif name in TASK_MANAGER_TOOLS:
        scan.task_manager.append({**base, "tool": name, "message_ids": [int(m) for m in _MESSAGE_ID_RE.findall(result)],
                            "item_ids": sorted({int(i) for i in _ITEM_ID_RE.findall(result)} | _input_items(call["input"]))})


def _input_items(args: Dict[str, Any]) -> set:
    out = set()
    for key in ("item_id", "id"):
        if isinstance(args.get(key), int):
            out.add(args[key])
    return out


def _json_object(text: str) -> Dict[str, Any]:
    start = text.find("{")
    if start < 0:
        return {}
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def scan_file(path: Path, lo: float, hi: float, conversation_id: str = "") -> Scan:
    return scan_records(iter_records(path, lo, hi), conversation_id)

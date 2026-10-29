#!/usr/bin/env python3
"""Build the synthetic fixture lines for tests/transcript_contract from a census (docs/transcript-contract.md).

    venv/bin/python3 scripts/transcript_contract/fixtures.py --census <dir>/census.json

writes ``tests/fixtures/transcript_contract/claude_lines.json`` and
``codex_lines.json``: ONE LINE PER SHAPE CLASS (every record type, system
subtype, queue operation, attachment kind, block type per role, tool_result
item type, codex line and payload type), each carrying EVERY key the census
measured for that shape with a PLACEHOLDER value of the measured JSON type.

SYNTHETIC BY CONSTRUCTION: the census holds key names and type names only, so
no value from a real transcript can reach a fixture. A string is ``"<str>"``,
a number ``0``, an object ``{}``; only discriminators (``type``, ``subtype``,
``operation``, ``role``) carry their real token. The files are ``.json``
because ``.gitignore`` keeps every ``*.jsonl`` out of the repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "tests" / "fixtures" / "transcript_contract"

PLACEHOLDER: Dict[str, Any] = {
    "string": "<str>", "integer": 0, "number": 0.5, "boolean": False,
    "null": None, "object": {}, "array": [],
}

CODEX_DECLARED: List[Dict[str, Any]] = [
    {"timestamp": "<str>", "type": "event_msg", "payload": {"type": "turn_aborted", "reason": "<str>"}},
    {"timestamp": "<str>", "type": "event_msg", "payload": {"type": "agent_reasoning", "text": "<str>"}},
    {"timestamp": "<str>", "type": "event_msg", "payload": {"type": "error", "message": "<str>"}},
    {"timestamp": "<str>", "type": "response_item",
     "payload": {"type": "local_shell_call", "call_id": "<str>", "status": "<str>", "action": {}}},
    {"type": "message", "role": "user", "content": []},
    {"record_type": "state"},
]


def _value(types: Mapping[str, int]) -> Any:
    ranked = sorted(types.items(), key=lambda kv: -kv[1])
    for name, _count in ranked:
        if name != "null":
            return PLACEHOLDER[name]
    return None


def _shape(census: Mapping[str, Any], key: str, **override: Any) -> Dict[str, Any]:
    table = census["shapes"][key]["keys"]
    body = {k: _value(v["types"]) for k, v in table.items() if not k.startswith("<")}
    body.update(override)
    return body


def _blank_text_block() -> Dict[str, Any]:
    return {"type": "text", "text": "<str>"}


def claude_lines(census: Mapping[str, Any]) -> List[Dict[str, Any]]:
    shapes = census["shapes"]
    out: List[Dict[str, Any]] = []

    def add(shape: str, obj: Dict[str, Any]) -> None:
        out.append({"shape": shape, "line": json.dumps(obj, separators=(",", ":"))})

    usage = _shape(census, "claude:message.usage")

    def assistant(block: Dict[str, Any]) -> Dict[str, Any]:
        msg = _shape(census, "claude:assistant.message:*", role="assistant", content=[block],
                     usage=usage, type="message")
        return _shape(census, "claude:record:assistant", type="assistant", message=msg)

    def user(content: Any) -> Dict[str, Any]:
        msg = _shape(census, "claude:user.message:*", role="user", content=content)
        return _shape(census, "claude:record:user", type="user", message=msg)

    def block(role: str, btype: str) -> Dict[str, Any]:
        body = _shape(census, f"claude:block:{role}:{btype}", type=btype)
        if btype in ("image", "document"):
            body["source"] = _shape(census, f"claude:block_source:{btype}:base64", type="base64")
        return body

    for key in shapes:
        parts = key.split(":")
        if key.startswith("claude:record:") and parts[2] not in ("assistant", "user", "attachment"):
            body = _shape(census, key, type=parts[2])
            if parts[2] == "system":
                body.pop("subtype", None)
            if parts[2] == "queue-operation":
                body["operation"] = "enqueue"
            add(f"record:{parts[2]}", body)
        elif key.startswith("claude:block:assistant:"):
            add(f"block:assistant:{parts[3]}", assistant(block("assistant", parts[3])))
        elif key.startswith("claude:block:user:"):
            body = block("user", parts[3])
            if parts[3] == "tool_result":
                body["content"] = "<str>"
            add(f"block:user:{parts[3]}", user([body]))
        elif key.startswith("claude:tool_result_item:"):
            item = _shape(census, key, type=parts[2])
            if parts[2] in ("image", "document"):
                item["source"] = _shape(census, "claude:block_source:image:base64", type="base64")
            result = dict(block("user", "tool_result"), content=[item])
            add(f"tool_result_item:{parts[2]}", user([result]))
        elif key.startswith("claude:system:"):
            add(f"system:{parts[2]}", _shape(census, key, type="system", subtype=parts[2]))
        elif key.startswith("claude:attachment.attachment:"):
            body = _shape(census, key, type=parts[2])
            add(f"attachment:{parts[2]}",
                _shape(census, "claude:record:attachment", type="attachment", attachment=body))
    add("record:assistant", assistant(_blank_text_block()))
    add("record:user", user([_blank_text_block()]))
    add("user:content_string", user("<str>"))
    for op in census["enums"].get("claude:queue-operation:operation", {}):
        add(f"queue_operation:{op}",
            _shape(census, "claude:record:queue-operation", type="queue-operation", operation=op))
    return sorted(out, key=lambda row: row["shape"])


def codex_lines(census: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key in census["shapes"]:
        parts = key.split(":")
        if not key.startswith("codex:payload:") or key.endswith(".info"):
            continue
        ltype, ptype = parts[2], parts[3]
        override: Dict[str, Any] = {} if ptype == "<no-type>" else {"type": ptype}
        payload = _shape(census, key, **override)
        if ptype == "token_count":
            payload["info"] = _shape(census, f"{key}.info")
        line = {"timestamp": "<str>", "type": ltype, "payload": payload}
        shape = ltype if ptype == "<no-type>" else f"{ltype}:{ptype}"
        out.append({"shape": shape, "line": json.dumps(line, separators=(",", ":"))})
    for obj in CODEX_DECLARED:
        payload = obj.get("payload", obj)
        name = payload.get("type") or payload.get("record_type")
        prefix = obj["type"] if "payload" in obj else "legacy"
        out.append({"shape": f"{prefix}:{name}", "line": json.dumps(obj, separators=(",", ":"))})
    return sorted(out, key=lambda row: row["shape"])


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--census", required=True, type=Path)
    args = parser.parse_args(argv)
    census = json.loads(args.census.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in (("claude_lines.json", claude_lines(census)),
                       ("codex_lines.json", codex_lines(census))):
        doc = {"generated_from": census.get("measured_at"), "synthetic": True, "lines": rows}
        (OUT / name).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        print(f"fixtures: {name} {len(rows)} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())

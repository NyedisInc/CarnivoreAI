
from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, TypeVar

from src.core.subagents.contract import (
    SHAPE_OK,
    SHAPE_UNRECOGNIZED,
    ShapeCheck,
    json_type_name,
    value_matches,
)
from src.core.subagents.shape_alert import register_contract_source, report_unrecognized

TRANSCRIPT_LINE_CONTRACT_VERSION: int = 1

MEASURED_AGAINST_CLAUDE_CODE: str = "2.1.199 to 2.1.283"
MEASURED_ON: str = "not measured"

FILE_KIND_TRANSCRIPT: str = "transcript_line"

_Table = Mapping[str, Tuple[type, ...]]

ENVELOPE_REQUIRED: _Table = {"type": (str,), "timestamp": (str,)}

RECORD_KEYS: Mapping[str, Tuple[_Table, _Table]] = {
    "assistant": ({"message": (dict,)}, {"isSidechain": (bool,)}),
    "user": (
        {"message": (dict,)},
        {"isMeta": (bool,), "isSidechain": (bool,), "promptSource": (str,),
         "origin": (dict,), "toolUseResult": (dict, list, str)},
    ),
    "system": ({"subtype": (str,)}, {"content": (str,)}),
    "queue-operation": ({"operation": (str,)}, {"content": (str,)}),
    "attachment": ({"attachment": (dict,)}, {}),
}

MESSAGE_CONTENT: Mapping[str, Tuple[type, ...]] = {
    "assistant": (list,),
    "user": (str, list),
}

BLOCK_KEYS: Mapping[str, Tuple[_Table, _Table]] = {
    "tool_use": ({"id": (str,), "name": (str,)}, {}),
    "tool_result": ({"tool_use_id": (str,)}, {"content": (str, list)}),
    "text": ({"text": (str,)}, {}),
}

TURN_END_REQUIRED: _Table = {"version": (str,)}
TURN_END_OPTIONAL: _Table = {
    "pendingBackgroundAgentCount": (int,),
    "pendingWorkflowCount": (int,),
}

ORIGIN_OPTIONAL: _Table = {"kind": (str,)}

ATTACHMENT_REQUIRED: _Table = {"type": (str,)}
QUEUED_COMMAND_REQUIRED: _Table = {"prompt": (str, list)}

TOOL_USE_RESULT_OPTIONAL: _Table = {
    "isAsync": (bool,),
    "agentId": (str,),
    "status": (str,),
    "taskType": (str,),
    "taskId": (str,),
    "backgroundTaskId": (str,),
    "persistent": (bool,),
    "timeoutMs": (int,),
    "task_id": (str,),
    "task_type": (str,),
}

TOOL_USE_RESULT_TASK_KEYS: Tuple[str, ...] = (
    "agentId", "isAsync", "taskType", "taskId", "backgroundTaskId",
    "task_id", "task_type",
)

register_contract_source(
    FILE_KIND_TRANSCRIPT,
    "src/core/attention/transcript_contract.py",
    'docs/jsonl-shape-inventory.md, addendum "main transcript lines the watcher reads"',
    MEASURED_AGAINST_CLAUDE_CODE,
)


def _keys(document: Dict[str, Any], path: str, required: _Table, optional: _Table,
          problems: List[str]) -> None:
    for key, types in required.items():
        if key not in document:
            problems.append(f"required key {path}{key} absent")
        elif not value_matches(document[key], types):
            problems.append(f"key {path}{key} is {json_type_name(document[key])}")
    for key, types in optional.items():
        if key in document and not value_matches(document[key], types):
            problems.append(f"key {path}{key} is {json_type_name(document[key])}")


def _blocks(content: Any, problems: List[str]) -> None:
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            problems.append(f"a message.content block is {json_type_name(block)}")
            continue
        kind = block.get("type")
        if not isinstance(kind, str):
            problems.append(f"key message.content[].type is {json_type_name(kind)}")
            continue
        tables = BLOCK_KEYS.get(kind)
        if tables is not None:
            _keys(block, f"message.content[{kind}].", tables[0], tables[1], problems)


def check_transcript_line(document: Any) -> Optional[ShapeCheck]:
    problems: List[str] = []
    if not isinstance(document, dict):
        problems.append(f"top level is {json_type_name(document)}, expected object")
        return _result(problems)
    kind = document.get("type")
    if not isinstance(kind, str):
        problems.append("required key type absent" if "type" not in document
                        else f"key type is {json_type_name(kind)}")
        return _result(problems)
    tables = RECORD_KEYS.get(kind)
    if tables is None:
        return None
    _keys(document, "", ENVELOPE_REQUIRED, {}, problems)
    _keys(document, "", tables[0], tables[1], problems)
    message = document.get("message")
    if kind in MESSAGE_CONTENT and isinstance(message, dict):
        _keys(message, "message.", {"content": MESSAGE_CONTENT[kind]}, {}, problems)
        _blocks(message.get("content"), problems)
    if kind == "system" and document.get("subtype") == "turn_duration":
        _keys(document, "", TURN_END_REQUIRED, TURN_END_OPTIONAL, problems)
    if kind == "user":
        if isinstance(document.get("origin"), dict):
            _keys(document["origin"], "origin.", {}, ORIGIN_OPTIONAL, problems)
        result = document.get("toolUseResult")
        if isinstance(result, dict) and any(key in result for key in TOOL_USE_RESULT_TASK_KEYS):
            _keys(result, "toolUseResult.", {}, TOOL_USE_RESULT_OPTIONAL, problems)
    attachment = document.get("attachment")
    if kind == "attachment" and isinstance(attachment, dict):
        _keys(attachment, "attachment.", ATTACHMENT_REQUIRED, {}, problems)
        if attachment.get("type") == "queued_command":
            _keys(attachment, "attachment.", QUEUED_COMMAND_REQUIRED, {}, problems)
    return _result(problems)


def _result(problems: List[str]) -> ShapeCheck:
    ordered = tuple(sorted(set(problems)))
    outcome = SHAPE_UNRECOGNIZED if ordered else SHAPE_OK
    return ShapeCheck(FILE_KIND_TRANSCRIPT, TRANSCRIPT_LINE_CONTRACT_VERSION,
                      outcome, ordered)


def check_window(records: Sequence[Any], *, report: bool = True) -> Tuple[str, ...]:
    found: set = set()
    for record in records or ():
        check = check_transcript_line(record)
        if check is None or check.recognized:
            continue
        found.update(check.problems)
        if report:
            version = record.get("version") if isinstance(record, dict) else None
            report_unrecognized(check, claude_code_version=version)
    return tuple(sorted(found))


_Facts = TypeVar("_Facts")


def against_contract(facts: _Facts, records: Sequence[Any], verdict: str) -> _Facts:
    problems = check_window(records)
    if not problems:
        return facts
    return replace(
        facts, verdict=verdict, pending_background_agents=None,
        pending_field_present=False, pending_workflows=None, shape_problems=problems,
        detail="the transcript does not match its shape contract (%s), so no "
        "count is believed; %s" % ("; ".join(problems), getattr(facts, "detail", "")),
    )


def contract_versions() -> Dict[str, int]:
    return {FILE_KIND_TRANSCRIPT: TRANSCRIPT_LINE_CONTRACT_VERSION}


__all__ = [
    "FILE_KIND_TRANSCRIPT", "SHAPE_OK", "SHAPE_UNRECOGNIZED", "ShapeCheck",
    "TRANSCRIPT_LINE_CONTRACT_VERSION", "against_contract", "check_transcript_line",
    "check_window",
    "contract_versions",
]


from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from src.core.attention.registry_record import MIN_PENDING_VERSION, format_version, parse_version

PENDING_AGENTS_FIELD: str = "pendingBackgroundAgentCount"

PENDING_WORKFLOWS_FIELD: str = "pendingWorkflowCount"

MIN_WORKFLOW_VERSION: Tuple[int, int, int] = (2, 1, 234)

RECORD_VERSION_FIELD: str = "version"

ASYNC_LAUNCHED_STATUS: str = "async_launched"

WORKFLOW_TASK_TYPE: str = "local_workflow"

BACKGROUND_SHELL_ID_FIELD: str = "backgroundTaskId"

MONITOR_PERSISTENT_FIELD: str = "persistent"

STOP_TASK_ID_FIELD: str = "task_id"
STOP_TASK_TYPE_FIELD: str = "task_type"

KIND_AGENT: str = "agent"
KIND_WORKFLOW: str = "workflow"
KIND_SHELL: str = "shell"
KIND_MONITOR: str = "monitor"

TURN_END_COUNTED_KINDS: frozenset = frozenset({KIND_AGENT, KIND_WORKFLOW})


def content_blocks(record: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [
        block
        for block in content
        if isinstance(block, dict) and block.get("type") == kind
    ]


def decode_pending_count(
    turn_end: Dict[str, Any],
    field: str,
    floor: Tuple[int, int, int],
    noun: str,
) -> Tuple[Optional[int], bool, str]:
    record_version = parse_version(turn_end.get(RECORD_VERSION_FIELD))
    if field in turn_end:
        raw = turn_end.get(field)
        is_count = isinstance(raw, int) and not isinstance(raw, bool)
        if not is_count or raw < 0:
            return (
                None,
                True,
                "the turn-end record carries a pending %s count that is %s, "
                "so that count is unknown"
                % (noun, "negative" if is_count else "not a number"),
            )
        return raw, True, ""
    if record_version is not None and record_version >= floor:
        return (
            0,
            False,
            "the turn-end record on claude %s omits the pending %s field, "
            "which that harness does only when the count is zero"
            % (format_version(record_version), noun),
        )
    return (
        None,
        False,
        "the turn-end record carries no pending %s field and names no claude "
        "version at or above %s, so that count is unknown rather than zero"
        % (noun, format_version(floor)),
    )


def decode_turn_end_counts(
    turn_end: Dict[str, Any],
) -> Tuple[Optional[int], bool, Optional[int], List[str]]:
    agents, agents_present, agent_note = decode_pending_count(
        turn_end, PENDING_AGENTS_FIELD, MIN_PENDING_VERSION, "background agent"
    )
    workflows, _, workflow_note = decode_pending_count(
        turn_end, PENDING_WORKFLOWS_FIELD, MIN_WORKFLOW_VERSION, "workflow"
    )
    notes = [note for note in (agent_note, workflow_note) if note]
    return agents, agents_present, workflows, notes


class Launch(NamedTuple):

    key: str
    kind: str
    task_id: Optional[str]
    tool_use_id: Optional[str]


def async_launch(record: Dict[str, Any]) -> Optional[Launch]:
    result = record.get("toolUseResult")
    if not isinstance(result, dict):
        return None
    if result.get("isAsync") is True:
        kind, task_id = KIND_AGENT, result.get("agentId")
    elif (
        result.get("status") == ASYNC_LAUNCHED_STATUS
        and result.get("taskType") == WORKFLOW_TASK_TYPE
    ):
        kind, task_id = KIND_WORKFLOW, result.get("taskId")
    elif BACKGROUND_SHELL_ID_FIELD in result:
        kind, task_id = KIND_SHELL, result.get(BACKGROUND_SHELL_ID_FIELD)
    elif MONITOR_PERSISTENT_FIELD in result and "taskId" in result:
        kind, task_id = KIND_MONITOR, result.get("taskId")
    else:
        return None
    task_id = task_id if isinstance(task_id, str) and task_id else None
    tool_use_id: Optional[str] = None
    for block in content_blocks(record, "tool_result"):
        candidate = block.get("tool_use_id")
        if isinstance(candidate, str) and candidate:
            tool_use_id = candidate
    key = tool_use_id or task_id
    if key is None:
        return None
    return Launch(key, kind, task_id, tool_use_id)


def stopped_task_id(record: Dict[str, Any]) -> Optional[str]:
    result = record.get("toolUseResult")
    if not isinstance(result, dict) or STOP_TASK_TYPE_FIELD not in result:
        return None
    task_id = result.get(STOP_TASK_ID_FIELD)
    return task_id if isinstance(task_id, str) and task_id else None

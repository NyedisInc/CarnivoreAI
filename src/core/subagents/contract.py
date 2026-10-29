
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple

SUBAGENT_META_CONTRACT_VERSION: int = 1
SUBAGENT_LINE_CONTRACT_VERSION: int = 1

MEASURED_AGAINST_CLAUDE_CODE: str = "2.1.283"
MEASURED_ON: str = "not measured"

FILE_KIND_META: str = "subagent_meta"
FILE_KIND_LINE: str = "subagent_jsonl"

SHAPE_OK: str = "ok"
SHAPE_UNRECOGNIZED: str = "shape_unrecognized"

META_REQUIRED: Mapping[str, Tuple[type, ...]] = {
    "agentType": (str,),
}
META_OPTIONAL: Mapping[str, Tuple[type, ...]] = {
    "description": (str,),
    "toolUseId": (str,),
    "spawnDepth": (int,),
    "model": (str,),
    "requestShape": (str,),
    "requestNonInteractive": (bool,),
    "parentAgentId": (str,),
    "stoppedByUser": (bool,),
    "worktreeCleanlyRemoved": (bool,),
    "worktreePath": (str,),
    "worktreeBranch": (str,),
    "spawnedWithWorktree": (bool,),
    "inheritedWorktreePath": (str,),
}

LINE_REQUIRED: Mapping[str, Tuple[type, ...]] = {
    "type": (str,),
    "timestamp": (str,),
    "agentId": (str,),
    "isSidechain": (bool,),
    "sessionId": (str,),
}

LINE_BOOKKEEPING_KINDS: Tuple[str, ...] = (
    "fork-context-ref",
    "api-request",
    "api-request-shape",
    "api-request-blob",
)
LINE_BOOKKEEPING_REQUIRED: Mapping[str, Tuple[type, ...]] = {
    "type": (str,),
    "agentId": (str,),
}


@dataclass(frozen=True)
class ShapeCheck:

    file_kind: str
    version: int
    outcome: str
    problems: Tuple[str, ...] = ()
    unknown_keys: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def recognized(self) -> bool:
        return self.outcome == SHAPE_OK


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _matches(value: Any, types: Tuple[type, ...]) -> bool:
    if isinstance(value, bool) and bool not in types:
        return False
    return isinstance(value, types)


def _check(
    document: Any,
    *,
    file_kind: str,
    version: int,
    required: Mapping[str, Tuple[type, ...]],
    optional: Mapping[str, Tuple[type, ...]],
    report_unknown: bool,
) -> ShapeCheck:
    if not isinstance(document, dict):
        return ShapeCheck(file_kind, version, SHAPE_UNRECOGNIZED,
                          (f"top level is {_type_name(document)}, expected object",))
    problems = []
    for key, types in required.items():
        if key not in document:
            problems.append(f"required key {key} absent")
        elif not _matches(document[key], types):
            problems.append(f"key {key} is {_type_name(document[key])}")
    for key, types in optional.items():
        if key in document and not _matches(document[key], types):
            problems.append(f"key {key} is {_type_name(document[key])}")
    unknown: Tuple[str, ...] = ()
    if report_unknown:
        known = set(required) | set(optional)
        unknown = tuple(sorted(str(key) for key in document if key not in known))
    outcome = SHAPE_UNRECOGNIZED if problems else SHAPE_OK
    return ShapeCheck(file_kind, version, outcome, tuple(problems), unknown)


check_document = _check

json_type_name = _type_name
value_matches = _matches


def check_meta(document: Any) -> ShapeCheck:
    return _check(document, file_kind=FILE_KIND_META,
                  version=SUBAGENT_META_CONTRACT_VERSION,
                  required=META_REQUIRED, optional=META_OPTIONAL,
                  report_unknown=True)


def check_line(document: Any) -> ShapeCheck:
    bookkeeping = (isinstance(document, dict)
                   and document.get("type") in LINE_BOOKKEEPING_KINDS)
    return _check(document, file_kind=FILE_KIND_LINE,
                  version=SUBAGENT_LINE_CONTRACT_VERSION,
                  required=LINE_BOOKKEEPING_REQUIRED if bookkeeping else LINE_REQUIRED,
                  optional={}, report_unknown=False)


def contract_versions() -> Dict[str, int]:
    return {
        FILE_KIND_META: SUBAGENT_META_CONTRACT_VERSION,
        FILE_KIND_LINE: SUBAGENT_LINE_CONTRACT_VERSION,
    }

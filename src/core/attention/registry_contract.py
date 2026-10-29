
from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from src.core.subagents.contract import (
    SHAPE_OK,
    SHAPE_UNRECOGNIZED,
    ShapeCheck,
    check_document,
)
from src.core.subagents.shape_alert import register_contract_source

REGISTRY_RECORD_CONTRACT_VERSION: int = 1

MEASURED_AGAINST_CLAUDE_CODE: str = "2.1.282 to 2.1.283"
MEASURED_ON: str = "2026-09-27"

FILE_KIND_REGISTRY: str = "pid_registry"

REGISTRY_REQUIRED: Mapping[str, Tuple[type, ...]] = {
    "status": (str,),
}
_NULL = type(None)
REGISTRY_OPTIONAL: Mapping[str, Tuple[type, ...]] = {
    "waitingFor": (str, _NULL),
    "sessionId": (str, _NULL),
    "tmux": (str, _NULL),
    "cwd": (str, _NULL),
    "name": (str, _NULL),
    "nameSource": (str, _NULL),
    "startedAt": (int, _NULL),
    "statusUpdatedAt": (int, _NULL),
    "nameSince": (int, _NULL),
}

register_contract_source(
    FILE_KIND_REGISTRY,
    "src/core/attention/registry_contract.py",
    'docs/jsonl-shape-inventory.md, addendum "pid registry record"',
    MEASURED_AGAINST_CLAUDE_CODE,
)


def check_registry_record(document: Any) -> ShapeCheck:
    return check_document(document, file_kind=FILE_KIND_REGISTRY,
                          version=REGISTRY_RECORD_CONTRACT_VERSION,
                          required=REGISTRY_REQUIRED, optional=REGISTRY_OPTIONAL,
                          report_unknown=True)


def contract_versions() -> Dict[str, int]:
    return {FILE_KIND_REGISTRY: REGISTRY_RECORD_CONTRACT_VERSION}


__all__ = [
    "FILE_KIND_REGISTRY", "REGISTRY_RECORD_CONTRACT_VERSION", "SHAPE_OK",
    "SHAPE_UNRECOGNIZED", "ShapeCheck", "check_registry_record",
    "contract_versions",
]

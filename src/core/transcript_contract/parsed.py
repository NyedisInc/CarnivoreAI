
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from src.core.transcript_contract.fields import Finding

STATUS_OK = "ok"
STATUS_BLANK = "blank"
STATUS_UNPARSEABLE = "unparseable"
STATUS_NON_OBJECT = "non_object"

FAMILY_CLAUDE = "claude"
FAMILY_CODEX = "codex"


@dataclass(frozen=True)
class UnknownRecord:

    type: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class ParsedLine:

    family: str
    status: str
    kind: str = ""
    record: Any = None
    known: bool = False
    findings: Tuple[Finding, ...] = field(default=())
    raw: Optional[Mapping[str, Any]] = None
    text: str = ""

    @property
    def clean(self) -> bool:
        return self.status == STATUS_OK and self.known and not self.findings

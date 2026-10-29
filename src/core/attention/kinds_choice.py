
from __future__ import annotations

import re
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator, model_serializer

KIND_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

MAX_KINDS = 64


class AttentionKindsChoice(BaseModel):
    """One surface's choice. ``all`` is the master check; ``kinds`` maps a kind id to its own check. Absent reads as on."""

    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    all: Optional[StrictBool] = None
    kinds: Optional[Dict[str, StrictBool]] = None

    @field_validator("kinds")
    @classmethod
    def _kinds(cls, value: Optional[Dict[str, bool]]) -> Optional[Dict[str, bool]]:
        if value is None:
            return None
        if len(value) > MAX_KINDS:
            raise ValueError(f"kinds holds at most {MAX_KINDS} kinds")
        for kind_id in value:
            if not KIND_ID_RE.match(kind_id):
                raise ValueError("kinds are keyed by kind ids like 'approvals' or 'alert_backup_health'")
        return dict(value)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: Any) -> Dict[str, Any]:
        return {key: value for key, value in handler(self).items() if value is not None}

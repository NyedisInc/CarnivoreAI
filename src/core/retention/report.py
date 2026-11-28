
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

PLANNED, DONE, SKIPPED, FAILED = "planned", "done", "skipped", "failed"


@dataclass
class Action:

    task: str
    op: str
    source: Path
    dest: Optional[Path]
    bytes: Optional[int]
    status: str = PLANNED
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["source"], out["dest"] = str(self.source), (str(self.dest) if self.dest else None)
        return out


@dataclass
class RetentionReport:

    started_at: str
    dry_run: bool
    drive_ready: bool = False
    drive_detail: str = ""
    actions: List[Action] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for action in self.actions:
            out[action.status] = out.get(action.status, 0) + 1
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {"started_at": self.started_at, "dry_run": self.dry_run, "drive_ready": self.drive_ready,
                "drive_detail": self.drive_detail, "counts": self.counts(), "errors": list(self.errors),
                "actions": [a.to_dict() for a in self.actions]}


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

CAP_SESSION_PLACE = "pack.session_place"
REASON_MAX = 160
FAMILIES = ("claude", "codex", "shell")


@dataclass(frozen=True)
class PlaceRequest:

    project: Optional[str] = None
    working_dir: Optional[str] = None
    family: str = "claude"
    needs: List[str] = field(default_factory=list)
    profile_name: Optional[str] = None


@dataclass(frozen=True)
class Starter:

    kind: Literal["owner", "agent", "automation"] = "owner"
    session_id: Optional[str] = None
    account_key: Optional[str] = None
    posture: str = "unknown"
    model: Optional[str] = None


@dataclass
class SessionPlacement:

    decision: Literal["here", "remote", "refused"]
    reason: str
    install_id: Optional[str] = None
    label: Optional[str] = None
    copy_root: Optional[str] = None
    code: Optional[str] = None
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    detail: str = ""
    project_uid: str = ""
    project_name: str = ""

    def wire(self) -> Dict[str, Any]:
        return {"decision": self.decision, "computer": self.install_id, "label": self.label, "reason": self.reason, "code": self.code}

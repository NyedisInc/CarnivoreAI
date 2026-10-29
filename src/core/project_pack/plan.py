
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

FINGERPRINT_CHARS = 16


@dataclass
class PackPlan:

    kind: str
    project: Dict[str, Any]
    checks: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    sizes: Dict[str, Any] = field(default_factory=dict)
    largest_folders: List[Dict[str, Any]] = field(default_factory=list)
    repos: List[Dict[str, Any]] = field(default_factory=list)
    children: List[Dict[str, Any]] = field(default_factory=list)
    local_only: List[str] = field(default_factory=list)
    integrity: Dict[str, Any] | None = None
    material: Dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""

    @property
    def root(self) -> str:
        return self.project["root"]

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c["ok"] for c in self.checks)

    def failed(self) -> List[str]:
        return [c["message"] for c in self.checks if not c["ok"]]

    def check(self, check_id: str, ok: bool, message: str) -> bool:
        self.checks.append({"id": check_id, "ok": bool(ok), "message": message})
        return bool(ok)

    def seal(self) -> None:
        blob = json.dumps(self.material, sort_keys=True, separators=(",", ":"), default=list)
        self.fingerprint = hashlib.sha256(blob.encode("utf-8", "surrogateescape")).hexdigest()[:FINGERPRINT_CHARS]

    def as_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "project": self.project, "ok": self.ok, "checks": self.checks,
                "warnings": self.warnings, "sizes": self.sizes, "largest_folders": self.largest_folders,
                "repos": self.repos, "children": self.children, "local_only": self.local_only,
                "integrity": self.integrity, "fingerprint": self.fingerprint}

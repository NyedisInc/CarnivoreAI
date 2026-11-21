
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.core.new_project.org_tree import inside_root
from src.core.project_directory import canonical_path
from src.core.session_project_binding import fold_path

BLOCK, WARN, OK = "block", "warn", "ok"
SCRATCH_NAMES = frozenset({"scratch", "llmscratch", "tmp", "temp"})
ACCOUNTS_RELATIVE = (".carnivore", "accounts")


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    params: Dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"level": self.level, "code": self.code, "params": dict(self.params)}


@dataclass(frozen=True)
class Verdict:
    ok: bool
    path: str
    findings: List[Finding]

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "path": self.path, "findings": [f.as_dict() for f in self.findings]}


def system_temp_roots() -> List[str]:
    raw = ["/tmp", "/private/tmp", "/var/folders", tempfile.gettempdir()]
    return sorted({canonical_path(p) for p in raw})


def accounts_root(home: Optional[str] = None) -> str:
    return canonical_path(str(Path(home or os.path.expanduser("~"), *ACCOUNTS_RELATIVE)))


def _is_scratch(path: str, temp_roots: Sequence[str]) -> bool:
    if any(part.casefold() in SCRATCH_NAMES for part in Path(path).parts):
        return True
    return any(inside_root(path, canonical_path(root)) for root in temp_roots)


def _owner_of(path: str, companies: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    owners = [c for c in companies if c.get("folder") and inside_root(path, c["folder"])]
    return max(owners, key=lambda c: len(fold_path(c["folder"])), default=None)


def _project_findings(path: str, projects: Sequence[Dict[str, Any]]) -> List[Finding]:
    folded = fold_path(path)
    same = next((p for p in projects if fold_path(canonical_path(p["root"])) == folded), None)
    if same:
        return [Finding(BLOCK, "already_project", {"project": same["name"]})]
    inside = [p for p in projects if folded.startswith(fold_path(canonical_path(p["root"])) + "/")]
    if inside:
        nearest = max(inside, key=lambda p: len(canonical_path(p["root"])))
        return [Finding(WARN, "inside_project", {"project": nearest["name"]})]
    return []


def _company_findings(path: str, companies: Sequence[Dict[str, Any]], company_id: Optional[int]) -> List[Finding]:
    chosen = next((c for c in companies if c["id"] == company_id), None) if company_id is not None else None
    owner = _owner_of(path, companies)
    if chosen is None:
        return [Finding(WARN, "no_company")]
    out = [Finding(OK, "company", {"company": chosen["name"]})]
    if owner is not None and owner["id"] != chosen["id"]:
        out.append(Finding(WARN, "other_company", {"owner": owner["name"], "company": chosen["name"]}))
    return out


def check_landing(path: str, *, org_root: Optional[str], projects: Sequence[Dict[str, Any]],
                  companies: Sequence[Dict[str, Any]], company_id: Optional[int] = None,
                  temp_roots: Optional[Sequence[str]] = None, home: Optional[str] = None) -> Verdict:
    if not isinstance(path, str) or not path.strip():
        return Verdict(False, "", [Finding(BLOCK, "pick_folder")])
    real = canonical_path(path.strip())
    findings: List[Finding] = []
    if _is_scratch(real, system_temp_roots() if temp_roots is None else temp_roots):
        findings.append(Finding(BLOCK, "scratch"))
    if inside_root(real, accounts_root(home)):
        findings.append(Finding(BLOCK, "sign_in_folder"))
    findings.extend(_project_findings(real, projects))
    if org_root and not inside_root(real, org_root):
        findings.append(Finding(WARN, "outside_org"))
    if not any(f.level == BLOCK for f in findings):
        findings.extend(_company_findings(real, companies, company_id))
        if not any(f.level == WARN for f in findings):
            findings.append(Finding(OK, "clean"))
    return Verdict(not any(f.level == BLOCK for f in findings), real, findings)

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple


class FixRefused(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def plan_fix(run: Dict[str, Any], finding_id: str) -> Tuple[str, str, str]:
    report = run.get("report")
    if not isinstance(report, dict) or report.get("schema") != "scrooge/1":
        raise FixRefused("no_report")
    finding = next((f for f in report.get("findings", []) if f.get("finding_id") == finding_id), None)
    if finding is None:
        raise FixRefused("finding_not_found")
    project = next((p for p in report.get("projects", []) if p.get("project_id") == finding.get("project_id")), None)
    if project is not None and project.get("home_folder"):
        raise FixRefused("home_folder")
    if not finding.get("fix_prompt") or project is None:
        raise FixRefused("no_fix_prompt")
    if not Path(project["folder"]).is_dir():
        raise FixRefused("project_folder_missing")
    return project["folder"], finding["fix_prompt"], f"scrooge fix: {finding['title']}"[:80]

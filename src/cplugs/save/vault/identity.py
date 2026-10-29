
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class Identity:

    session_uuid: Optional[str] = None
    project_uid: Optional[str] = None
    project_name: Optional[str] = None
    working_dir: Optional[str] = None
    wrapper: Optional[str] = None
    title: Optional[str] = None


class ProjectIndex:

    def __init__(self, rows: Iterable[Dict[str, str]] = ()) -> None:
        self._rows: List[Dict[str, str]] = sorted((r for r in rows if r.get("root")), key=lambda r: len(r["root"]), reverse=True)

    def lookup(self, working_dir: Optional[str]) -> Optional[Dict[str, str]]:
        if not working_dir:
            return None
        folder = working_dir.rstrip("/")
        for row in self._rows:
            root = row["root"].rstrip("/")
            if folder == root or folder.startswith(root + "/"):
                return row
        return None

    def complete(self, identity: Identity) -> Identity:
        if identity.project_uid or not identity.working_dir:
            return identity
        row = self.lookup(identity.working_dir)
        if row is None:
            return identity
        return replace(identity, project_uid=row.get("uid"), project_name=identity.project_name or row.get("display_name"))


from __future__ import annotations

import os
import re
from contextlib import closing
from typing import Any, Optional

from src.core.mcp.common import ToolError

MISSING_FOLDER_CODES = ("working_dir_missing", "working_dir is not an existing directory")
_PLAIN_CODE = re.compile(r"[A-Za-z0-9_ ,.'-]{1,120}")


class SpawnReason(ToolError):
    pass


def replica_folder(folder: str, peer_install_id: str) -> Optional[str]:
    from src.api import projects_service
    from src.config import settings
    from src.core.pack.identity import replicas

    with closing(projects_service.open_db_or_503(settings)) as conn:
        for row in conn.execute("SELECT uid, root FROM projects WHERE root IS NOT NULL AND uid IS NOT NULL").fetchall():
            root = str(row[1]).rstrip("/")
            if root and (folder == root or folder.startswith(root + "/")):
                for rep in replicas.list_replicas(conn, row[0]):
                    if rep["install_id"] == peer_install_id and rep["state"] == "active" and rep["root"]:
                        return os.path.normpath(str(rep["root"]) + folder[len(root):])
    return None


def refusal_reason(label: str, answer: Any, status: int, folder: Optional[str]) -> SpawnReason:
    try:
        code = (answer.json().get("detail") or {}).get("code")
    except (ValueError, AttributeError):
        code = None
    if code in MISSING_FOLDER_CODES:
        return SpawnReason(f"{label} has no folder at {folder}; give a working_dir that exists on {label}, or a project {label} holds")
    if isinstance(code, str) and _PLAIN_CODE.fullmatch(code):
        return SpawnReason(f"{label} refused the spawn: {code}")
    return SpawnReason(f"{label} refused spawn ({status})")


def missing_folder(answer: Any) -> bool:
    try:
        return (answer.json().get("detail") or {}).get("code") in MISSING_FOLDER_CODES
    except (ValueError, AttributeError):
        return False

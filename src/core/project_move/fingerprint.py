
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, Optional, Tuple

FINGERPRINT_CHARS = 16


class FingerprintError(Exception):

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def folder_identity(path: Optional[str]) -> Optional[Tuple[int, int]]:
    if not path:
        return None
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_dev, info.st_ino)


def plan_material(plan: Any) -> Dict[str, Any]:
    return {
        "project": plan.project["id"], "old_root": plan.old_root, "new_root": plan.new_root,
        "move_folder": plan.move_folder, "create_parents": plan.create_parents,
        "folders_to_create": list(plan.folders_to_create),
        "old_folder": folder_identity(plan.old_root), "new_folder": folder_identity(plan.new_root),
        "children": sorted((c["id"], c["old_root"], c["new_root"] or "") for c in plan.children),
        "sessions": sorted((s["id"], s["old_dir"], s["lifecycle"]) for s in plan.sessions),
        "conversation_rows": plan.conversation_rows, "skill_installs": dict(plan.skill_installs),
        "transcript_moves": [(m["from"], m["to"], m["mode"], m.get("files", 0)) for m in plan.transcript_moves],
    }


def plan_fingerprint(plan: Any) -> str:
    blob = json.dumps(plan_material(plan), sort_keys=True, separators=(",", ":"), default=list)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:FINGERPRINT_CHARS]


def require_quoted(plan: Any, quoted: Optional[str]) -> None:
    if not quoted or not quoted.strip():
        raise FingerprintError(428, "apply needs plan_fingerprint: ask for the plan first (apply false), "
                                    "read it, and send back its fingerprint")
    if quoted.strip() != plan.fingerprint:
        raise FingerprintError(412, "the plan changed since it was read (fingerprint "
                                    f"{quoted.strip()} is now {plan.fingerprint}); read the new plan and quote it")

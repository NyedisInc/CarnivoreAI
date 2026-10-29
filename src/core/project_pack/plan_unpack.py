
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict

from src.core.project_pack import archive_io, integrity, store
from src.core.project_pack import constants as K
from src.core.project_pack.env import PackEnv
from src.core.project_pack.plan import PackPlan
from src.core.project_pack.plan_pack import folder_identity


def _bare_root(plan: PackPlan, archive_name: str) -> None:
    allowed = {archive_name, K.MANIFEST_NAME, K.README_NAME}
    try:
        extra = [n for n in sorted(os.listdir(plan.root)) if n not in allowed]
    except OSError as exc:
        plan.check("folder_bare", False, f"cannot list the folder: {exc}")
        return
    plan.check("folder_bare", not extra, "the folder holds only the pack files" if not extra else
               "the folder holds other files, so unpacking would mix with them: " + ", ".join(extra[:8]))


def build_unpack_plan(conn: sqlite3.Connection, project: Dict[str, Any], *, env: PackEnv) -> PackPlan:
    root = project["root"]
    plan = PackPlan("unpack", {"id": project["id"], "name": project["display_name"], "root": root})
    row = store.get(conn, project["id"]) or {}
    state = row.get("state", K.STATE_UNPACKED)
    plan.check("state_packed", state == K.STATE_PACKED, "the folder is packed" if state == K.STATE_PACKED
               else f"the project is {state}, not packed")
    inside = row.get("packed_in")
    plan.check("not_a_child", not inside, "the folder is packed on its own" if not inside else
               f"this project was packed inside project {inside}; unpack that project instead")
    present = os.path.isdir(root)
    plan.check("root_present", present, "the folder is there" if present else "the folder is missing")
    verdict = integrity.cheap_check(root, row) if present and state == K.STATE_PACKED else None
    plan.integrity = verdict.as_dict() if verdict else None
    blocking = verdict is not None and verdict.status in (integrity.MISSING, integrity.UNREADABLE, integrity.CLOUD_ONLY)
    plan.check("archive_present", verdict is not None and not blocking, "the archive and manifest are there"
               if verdict is not None and not blocking else (verdict.message if verdict else "not measured"))
    if verdict is not None and verdict.status == integrity.MODIFIED:
        plan.warnings.append("WARNING: " + verdict.message + " The checksum is compared before anything is extracted.")
    if present and state == K.STATE_PACKED:
        _bare_root(plan, row.get("archive_name") or "")
    else:
        plan.check("folder_bare", False, "not measured")
    need = int(row.get("logical_bytes") or 0) + env.margin
    free = env.free_bytes(root) if present else 0
    plan.check("free_space", present and free >= need, f"{free} bytes free, {need} needed")
    probe = archive_io.probe_works()
    plan.check("tar_works", not probe, "tar can read zstd" if not probe else probe)
    plan.sizes = {"logical_bytes": row.get("logical_bytes"), "archive_bytes": row.get("archive_bytes"),
                  "file_count": row.get("file_count")}
    plan.material = {"kind": "unpack", "project": project["id"], "root": root, "identity": folder_identity(root),
                     "state": state, "archive": row.get("archive_name"), "sha256": row.get("archive_sha256"),
                     "bytes": row.get("archive_bytes"), "mtime_ns": row.get("archive_mtime_ns"),
                     "integrity": verdict.status if verdict else None}
    plan.seal()
    return plan


from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import structlog

from src.core.skill_manager.roots import make_key, profile_groups, project_dirs
from src.core.skill_manager.scan import MAX_SKILL_MD_BYTES, scan_root
from src.core.skill_manager.types import CLAUDE, CODEX, SCOPE_PERSONAL, SCOPE_PROJECT, Profile, SkillRoot

logger = structlog.get_logger()

MAX_SIGNATURE_ENTRIES = 2000
SIDECAR_NAME = ".carnivore-skill.json"

STATE_PRESENT, STATE_DIFFERS, STATE_ABSENT = "present", "differs", "absent"
STATE_NONE_YET, STATE_SHADOWED = "none_yet", "shadowed"


def folder_signature(path: str) -> Dict[str, Any]:
    entries: List[Tuple[str, int]] = []
    truncated = False
    for current, dirs, names in os.walk(path, followlinks=False):
        dirs.sort()
        for name in sorted(names):
            if name == SIDECAR_NAME and current == path:
                continue
            if len(entries) >= MAX_SIGNATURE_ENTRIES:
                truncated = True
                break
            full = os.path.join(current, name)
            try:
                size = os.lstat(full).st_size
            except OSError:
                size = -1
            entries.append((os.path.relpath(full, path), size))
        if truncated:
            break
    md5 = hashlib.sha256()
    skill_md = os.path.join(path, "SKILL.md")
    try:
        if os.path.islink(skill_md):
            md5.update(os.readlink(skill_md).encode("utf-8", errors="replace"))
        else:
            with open(skill_md, "rb") as handle:
                md5.update(handle.read(MAX_SKILL_MD_BYTES))
    except OSError as exc:
        logger.warning("command_center_skill_md_unreadable", error=type(exc).__name__)
    blob = json.dumps([entries, md5.hexdigest(), truncated], separators=(",", ":"))
    return {
        "digest": hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16],
        "files": len(entries),
        "bytes": sum(size for _, size in entries if size > 0),
        "truncated": truncated,
    }


def _ident(path: str) -> Any:
    try:
        info = os.stat(path)
    except OSError:
        return os.path.realpath(path)
    return (info.st_dev, info.st_ino)


def _column(
    kind: str, harness: str, scope: str, path: str, label: str, *,
    project_id: Optional[Any] = None, reason: Optional[str] = None, sharing: Sequence[str] = (),
) -> Dict[str, Any]:
    real = os.path.realpath(path)
    return {
        "column_id": make_key(kind, f"{harness}:{real}"),
        "harness": harness,
        "scope": scope,
        "project_id": project_id,
        "project_ids": [] if project_id is None else [project_id],
        "label": label,
        "path": real,
        "leaf": os.path.abspath(path),
        "exists": os.path.isdir(real),
        "writable": reason is None,
        "readonly_reason": reason,
        "accounts_sharing": list(sharing),
    }


def _personal_columns(profiles: Sequence[Profile], home: Path, codex_home: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for index, group in enumerate(profile_groups(profiles)):
        if index == 0:
            composed = str(home / ".claude" / "skills")
            leaf = composed if os.path.realpath(composed) == group.skills_path else group.skills_path
            out.append(_column("cp", CLAUDE, SCOPE_PERSONAL, leaf, "all projects (claude)", sharing=group.profiles))
        else:
            out.append(_column("cp", CLAUDE, SCOPE_PERSONAL, group.skills_path, f"login {', '.join(group.profiles)}",
                               reason="separate_login_folder", sharing=group.profiles))
    out.append(_column("cx", CODEX, SCOPE_PERSONAL, str(home / ".agents" / "skills"), "all projects (codex)"))
    for legacy in (codex_home / "skills", home / ".codex" / "skills"):
        if legacy.is_dir():
            out.append(_column("cx", CODEX, SCOPE_PERSONAL, str(legacy), "codex home", reason="legacy_codex_folder"))
    return out


def _project_columns(project: Dict[str, Any], home: Path) -> List[Dict[str, Any]]:
    real = os.path.realpath(str(project.get("root") or project.get("path")))
    home_rooted = real == os.path.realpath(str(home))
    chain = [] if home_rooted else project_dirs(real, home=home)
    folder = chain[-1] if chain else real
    reason = "home_folder" if home_rooted else ("archived" if project.get("archived_at") else None)
    kind = "ph" if home_rooted else "pj"
    label, pid = str(project.get("name") or os.path.basename(real)), project.get("id")
    cols = [
        _column(kind, CLAUDE, SCOPE_PROJECT, os.path.join(folder, ".claude", "skills"), label, project_id=pid, reason=reason),
        _column(kind, CODEX, SCOPE_PROJECT, os.path.join(folder, ".agents", "skills"), label, project_id=pid, reason=reason),
    ]
    legacy = os.path.join(folder, ".codex", "skills")
    if os.path.isdir(legacy):
        cols.append(_column(kind, CODEX, SCOPE_PROJECT, legacy, label, project_id=pid, reason=reason or "legacy_codex_folder"))
    return cols


def _merge_columns(columns: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for col in columns:
        have = merged.get(col["column_id"])
        if have is None:
            merged[col["column_id"]] = col
            continue
        have["project_ids"] += [p for p in col["project_ids"] if p not in have["project_ids"]]
        if have["readonly_reason"] == "archived" and col["readonly_reason"] is None:
            have.update(writable=True, readonly_reason=None, project_id=col["project_id"], label=col["label"])
    return list(merged.values())


def _generation(columns: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> str:
    parts = [f"{c['column_id']}\t{c['exists']}" for c in columns]
    for row in rows:
        for col_id, cells in row["cells"].items():
            parts += [f"{col_id}\t{row['name']}\t{c['folder']}\t{c['signature']}" for c in cells if c["folder"]]
    return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()


def build_command_center(
    *,
    profiles: Sequence[Profile],
    projects: Sequence[Dict[str, Any]],
    home: Path,
    codex_home: Path,
    read_ledger: Callable[[], Iterable[Tuple[str, str]]],
    include_archived: bool = False,
) -> Dict[str, Any]:
    """Build the whole matrix: columns, rows keyed by SKILL.md name, cells, and the generation stamp.

    Description: ``read_ledger`` is called EXACTLY ONCE per build and returns (install-target path, item_id) pairs the
      catalog ledger owns (a cell on one, matched by device and inode, is ``managed: "ledger"`` with its
      ``managed_item_id``). Archived projects appear only with
      ``include_archived`` and are read-only.
    Inputs: profiles - known Claude profiles. projects - project view rows (id, name, path, root, archived_at).
      home, codex_home - injected roots. read_ledger - the one ledger read. include_archived - archived toggle.
    Output: {generation, include_archived, columns[], rows[{name, description, cells{column_id: [cell, ...]}}]}.
      A cell is {state, location_id, folder, signature, files, bytes, managed, managed_item_id, shadowed_by}; a column with no skill
      of that name holds one cell, state ``absent`` (folder exists) or ``none_yet`` (folder does not exist yet).
    Example: build_command_center(profiles=ps, projects=rows, home=h, codex_home=c, read_ledger=lambda: [])["columns"]
    """
    live = [p for p in projects if include_archived or not p.get("archived_at")]
    columns = _merge_columns(
        _personal_columns(profiles, home, codex_home) + [c for p in live for c in _project_columns(p, home)]
    )
    managed = {_ident(path): item_id for path, item_id in read_ledger()}
    by_name: Dict[str, Dict[str, Any]] = {}
    scans: Dict[str, Any] = {}
    for col in columns:
        if col["path"] not in scans:
            skills, _refused = scan_root(SkillRoot(col["column_id"], col["harness"], col["scope"], col["path"]))
            scans[col["path"]] = skills
        for skill in scans[col["path"]]:
            row = by_name.setdefault(skill.name, {"name": skill.name, "description": skill.description, "cells": {}})
            sig = folder_signature(skill.path)
            row["cells"].setdefault(col["column_id"], []).append({
                "state": STATE_PRESENT,
                "location_id": f"{col['column_id']}:{skill.folder}",
                "folder": skill.folder,
                "signature": sig["digest"],
                "files": sig["files"],
                "bytes": sig["bytes"],
                "managed": "ledger" if _ident(skill.path) in managed else None,
                "managed_item_id": managed.get(_ident(skill.path)),
                "shadowed_by": None,
            })
    personal = next((c["column_id"] for c in columns if c["harness"] == CLAUDE and c["scope"] == SCOPE_PERSONAL and c["writable"]), None)
    rows = [by_name[name] for name in sorted(by_name)]
    for row in rows:
        reference = next((cells[0]["signature"] for c in columns for cells in [row["cells"].get(c["column_id"])] if cells), None)
        winner = (row["cells"].get(personal) or [None])[0]
        for col in columns:
            cells = row["cells"].get(col["column_id"])
            if not cells:
                row["cells"][col["column_id"]] = [{
                    "state": STATE_ABSENT if col["exists"] else STATE_NONE_YET, "location_id": None, "folder": None,
                    "signature": None, "files": 0, "bytes": 0, "managed": None, "managed_item_id": None, "shadowed_by": None,
                }]
                continue
            for cell in cells:
                cell["state"] = STATE_PRESENT if cell["signature"] == reference else STATE_DIFFERS
                if winner and col["harness"] == CLAUDE and col["scope"] == SCOPE_PROJECT:
                    cell["state"], cell["shadowed_by"] = STATE_SHADOWED, winner["location_id"]
    return {
        "generation": _generation(columns, rows),
        "include_archived": include_archived,
        "columns": columns,
        "rows": rows,
    }

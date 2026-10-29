
from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from src.core.blobcodec.place import sha256_file
from src.core.crate_format.constants import HOME_CLAUDE, HOME_CODEX, HOME_PROJECT, LINE_ROLES
from src.core.crate_format.model_files import FileRecord
from src.core.crate_format.reader import CrateReader
from src.core.crate_import.enc import EncEntry
from src.core.crate_import.model import COPY_ROLES
from src.core.crate_import.env import ImportEnv
from src.core.transcript_source.dataless import is_dataless_file

CLASS_ABSENT = "absent"
CLASS_SAME = "same"
CLASS_GROW = "grow"
CLASS_LOCAL_NEWER = "local_newer"
CLASS_CLOUD_ONLY = "cloud_only"
CLASS_CONFLICT = "conflict"
CLASS_UNSAFE = "unsafe"

ACT_PLACE = "place"
ACT_KEPT = "kept_in_crate"
ACT_DEFERRED = "deferred"
ACT_AFTER_ROWS = "after_rows"
ACT_SIDE_FOLDER = "side_folder"

CONVERSATION_ROLES = ("transcript", "orphan_transcript", "subagent", "tool_result", "conversation_file")
INSTRUCTION_ROLES = ("memory", "project_note", "plan")
DEFERRED_ROLES = ("swarm_desk",)
_CODEX_REL = re.compile(r"^sessions/\d{4}/\d{2}/\d{2}/rollout-[A-Za-z0-9._-]+\.jsonl$")
_TODO_REL = re.compile(r"^todos/[^/]+$")
_PLAN_REL = re.compile(r"^plans/[^/]+\.md$")
_HISTORY_REL = re.compile(r"^file-history/[^/]+/.+$")


@dataclass(frozen=True)
class Placement:

    record: FileRecord
    action: str
    dest: Optional[Path] = None
    cls: Optional[str] = None
    reason: str = ""
    home: Optional[Path] = None


def _split_projects_rel(rel: str) -> Optional[Tuple[str, str]]:
    parts = rel.split("/", 2)
    return (parts[1], parts[2]) if len(parts) == 3 and parts[0] == "projects" and parts[1] and parts[2] else None


def destination(record: FileRecord, env: ImportEnv, enc: Dict[str, EncEntry], *, own: bool, include_instructions: bool,
                include_project_files: bool = False, claude_home: Optional[Path] = None) -> Tuple[str, Optional[Path], str]:
    role = record.role
    if role in COPY_ROLES or record.rel.startswith("lines/"):
        return ACT_KEPT, None, "copy_role"
    if role in ("task_file", "plugin_file"):
        return ACT_AFTER_ROWS, None, role
    if role in ("project_file", "project_link") and record.home == HOME_PROJECT:
        return (ACT_SIDE_FOLDER, None, role) if include_project_files else (ACT_KEPT, None, "project_files_not_ticked")
    if role in DEFERRED_ROLES:
        return ACT_DEFERRED, None, role
    claude_home = claude_home or Path(env.claude_homes[0])
    if role in CONVERSATION_ROLES or role in ("memory", "project_note"):
        parsed = _split_projects_rel(record.rel) if record.home == HOME_CLAUDE else None
        if parsed is None:
            return ACT_KEPT, None, "off_allowlist"
        folder, rest = parsed
        if role in ("transcript", "orphan_transcript") and (record.conversation_id is None or rest != f"{record.conversation_id}.jsonl"):
            return ACT_KEPT, None, "off_allowlist"
        if role in ("subagent", "tool_result", "conversation_file") and (
                record.conversation_id is None or not rest.startswith(f"{record.conversation_id}/")):
            return ACT_KEPT, None, "off_allowlist"
        entry = enc.get(folder)
        if role in ("memory", "project_note"):
            if not (own or include_instructions):
                return ACT_KEPT, None, "instructions_held_back"
            if entry is None or folder != record.enc_folder or not rest.startswith("memory/"):
                return ACT_KEPT, None, "off_allowlist"
        return ACT_PLACE, claude_home / "projects" / (entry.target if entry is not None else folder) / rest, ""
    if role == "file_history" and record.home == HOME_CLAUDE and _HISTORY_REL.match(record.rel):
        return ACT_PLACE, claude_home / record.rel, ""
    if role == "todo" and record.home == HOME_CLAUDE and _TODO_REL.match(record.rel):
        return ACT_PLACE, claude_home / record.rel, ""
    if role == "plan" and record.home == HOME_CLAUDE and _PLAN_REL.match(record.rel):
        if not (own or include_instructions):
            return ACT_KEPT, None, "instructions_held_back"
        return ACT_PLACE, claude_home / record.rel, ""
    if role == "codex_rollout" and record.home == HOME_CODEX and _CODEX_REL.match(record.rel):
        return ACT_PLACE, Path(env.codex_home) / record.rel, ""
    return ACT_KEPT, None, "off_allowlist"


def contained(dest: Path, home: Path) -> Optional[str]:
    real_home = Path(os.path.realpath(home))
    try:
        relative = dest.relative_to(home)
    except ValueError:
        return "outside_home"
    current = real_home
    for part in relative.parts[:-1]:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            break
        except OSError:
            return "unreadable_part"
        if stat.S_ISLNK(mode):
            return "symlink_below_home"
        if not stat.S_ISDIR(mode):
            return "not_a_folder"
    return None


def _crate_prefix_sha(reader: CrateReader, record: FileRecord, count: int) -> str:
    digest, left = hashlib.sha256(), count
    for chunk in reader.file_chunks(record):
        piece = chunk[:left]
        digest.update(piece)
        left -= len(piece)
        if left <= 0:
            break
    return digest.hexdigest()


def _local_prefix_sha(path: Path, count: int) -> str:
    digest, left = hashlib.sha256(), count
    with open(path, "rb") as handle:
        while left > 0:
            block = handle.read(min(1024 * 1024, left))
            if not block:
                break
            digest.update(block)
            left -= len(block)
    return digest.hexdigest()


def grow_size(dest: Path, record: FileRecord, reader: CrateReader) -> Optional[int]:
    try:
        info = os.lstat(dest)
        if not stat.S_ISREG(info.st_mode) or is_dataless_file(dest) or not 0 < info.st_size < record.length:
            return None
        return info.st_size if _local_prefix_sha(dest, info.st_size) == _crate_prefix_sha(reader, record, info.st_size) else None
    except OSError:
        return None


def classify(dest: Path, record: FileRecord, reader: CrateReader) -> Tuple[str, str]:
    try:
        info = os.lstat(dest)
    except FileNotFoundError:
        return CLASS_ABSENT, ""
    except OSError:
        return CLASS_CONFLICT, "unreadable"
    if not stat.S_ISREG(info.st_mode):
        return CLASS_CONFLICT, "not_a_regular_file"
    if is_dataless_file(dest):
        return CLASS_CLOUD_ONLY, "local_cloud_only"
    size = info.st_size
    try:
        if size == record.length:
            return (CLASS_SAME, "") if sha256_file(dest) == record.content_sha256 else (CLASS_CONFLICT, "different_bytes")
        if size < record.length:
            line_mode = record.role in LINE_ROLES
            if line_mode and _local_prefix_sha(dest, size) == _crate_prefix_sha(reader, record, size):
                return CLASS_GROW, ""
            return CLASS_CONFLICT, "different_bytes"
        return (CLASS_LOCAL_NEWER, "") if _local_prefix_sha(dest, record.length) == record.content_sha256 else (CLASS_CONFLICT, "different_bytes")
    except OSError:
        return CLASS_CONFLICT, "unreadable"


def plan_files(reader: CrateReader, records: Iterable[FileRecord], env: ImportEnv, enc: Dict[str, EncEntry], *, own: bool,
               include_instructions: bool, excluded_conversations: frozenset = frozenset(),
               include_project_files: bool = False, conversation_homes: Optional[Mapping[str, Path]] = None) -> List[Placement]:
    out: List[Placement] = []
    homes = {HOME_CLAUDE: Path(env.claude_homes[0]), HOME_CODEX: Path(env.codex_home)}
    for record in records:
        if record.conversation_id in excluded_conversations:
            out.append(Placement(record, ACT_KEPT, reason="excluded"))
            continue
        pinned = (conversation_homes or {}).get(record.conversation_id or "") if record.home == HOME_CLAUDE else None
        action, dest, reason = destination(record, env, enc, own=own, include_instructions=include_instructions,
                                           include_project_files=include_project_files, claude_home=pinned)
        if action != ACT_PLACE or dest is None:
            out.append(Placement(record, action, reason=reason))
            continue
        problem = contained(dest, pinned if pinned is not None else homes[record.home])
        if problem is not None:
            out.append(Placement(record, ACT_KEPT, dest, CLASS_UNSAFE, problem))
            continue
        cls, why = classify(dest, record, reader)
        out.append(Placement(record, ACT_PLACE, dest, cls, why, pinned))
    return out

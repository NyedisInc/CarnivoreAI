
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.blobcodec.place import sha256_file
from src.core.crate_format.constants import HOME_PROJECT, M_PROJECT_PATCH, ROLE_PROJECT_FILE, ROLE_PROJECT_LINK
from src.core.crate_format.model_files import FileRecord
from src.core.crate_format.reader import CrateReader
from src.core.crate_import import target
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.model import (
    B_BAD_REQUEST, B_NO_SPACE, B_ROOT_REFUSED, MODE_RELOCATE, W_LINK_NOT_CREATED, W_PROJECT_FILE_KEPT, Collector, ImportRequest,
)
from src.core.crate_import.provenance import Provenance
from src.core.pack.migrate.receive import DISK_HEADROOM
from src.core.project_move.paths import is_within

PLACE_INTO_ROOT, PLACE_BESIDE, PLACE_HERE = "into_project_folder", "beside_project_folder", "already_here"
MAX_CLASH = 99
LINK_ABSOLUTE, LINK_ESCAPES, LINK_EMPTY, LINK_EXISTS, LINK_CHANGED = "absolute", "escapes_folder", "empty_target", "name_taken", "bytes_wrong"
LINK_VIA_LINK = "through_another_link"
_CONFIG = re.compile(r"(^|/)(\.claude/settings[^/]*\.json|\.mcp\.json|CLAUDE\.md)$")


@dataclass(frozen=True)
class LinkPlan:

    rel: str
    target: str
    record: FileRecord
    why: str = ""


@dataclass
class SidePlan:

    path: Path
    files: List[Tuple[FileRecord, Path]] = field(default_factory=list)
    links: List[LinkPlan] = field(default_factory=list)
    patch: bool = False
    git: Optional[Dict[str, Any]] = None
    bytes: int = 0
    claude_config: List[str] = field(default_factory=list)
    work_here: bool = False
    into_root: bool = False
    already_here: bool = False
    matching: int = 0
    differing: int = 0

    def view(self) -> Dict[str, Any]:
        git = {k: self.git.get(k) for k in ("branch", "head", "dirty", "detached")} if self.git else None
        return {"path": str(self.path), "files": len(self.files), "bytes": self.bytes,
                "links_created": sum(1 for link in self.links if not link.why),
                "links_listed": [{"rel": link.rel, "target": link.target, "why": link.why} for link in self.links if link.why],
                "claude_config": list(self.claude_config), "patch": self.patch, "git": git, "work_in_restored_copy": self.work_here,
                "placement": PLACE_HERE if self.already_here else (PLACE_INTO_ROOT if self.into_root else PLACE_BESIDE),
                "matching": self.matching, "differing": self.differing}


def project_records(files: List[FileRecord]) -> List[FileRecord]:
    return [f for f in files if f.home == HOME_PROJECT and f.role in (ROLE_PROJECT_FILE, ROLE_PROJECT_LINK)]


def safe_rel(rel: str) -> bool:
    parts = rel.split("/")
    return bool(rel) and not rel.startswith("/") and "\0" not in rel and all(p not in ("", ".", "..") for p in parts)


def link_verdict(rel: str, link_text: str, other_links: frozenset = frozenset()) -> str:
    if not link_text or "\0" in link_text:
        return LINK_EMPTY
    if os.path.isabs(link_text):
        return LINK_ABSOLUTE
    joined = os.path.join(os.path.dirname(rel), link_text)
    resolved = os.path.normpath(joined)
    if resolved == ".." or resolved.startswith("../"):
        return LINK_ESCAPES
    parts = [p for p in joined.split("/") if p not in ("", ".")]
    through = {"/".join(parts[:i]) for i in range(1, len(parts) + 1)} | {resolved}
    return LINK_VIA_LINK if (through & other_links) - {rel} else ""


def _base_root(crate: target.CrateProject, decision: target.TargetDecision, request: ImportRequest) -> Optional[str]:
    return decision.root_to if request.mode == MODE_RELOCATE else (crate.root or decision.root_to)


def root_is_free(root: Optional[str]) -> bool:
    if not root:
        return False
    if not os.path.lexists(root):
        return True
    if os.path.islink(root) or not os.path.isdir(root):
        return False
    with os.scandir(root) as entries:
        return next(entries, None) is None


def compare_with_disk(files: List[Tuple[FileRecord, Path]], links: List[LinkPlan], root: Path) -> Tuple[int, int]:
    real_root = os.path.realpath(root)
    same = other = 0
    for record, dest in files:
        try:
            ok = (is_within(os.path.realpath(dest), real_root) and not os.path.islink(dest) and os.path.isfile(dest)
                  and os.path.getsize(dest) == record.length and sha256_file(str(dest)) == record.content_sha256)
        except OSError:
            ok = False
        same, other = same + ok, other + (not ok)
    for link in (lk for lk in links if not lk.why):
        dest = root / link.rel
        ok = os.path.islink(dest) and os.readlink(dest) == link.target
        same, other = same + ok, other + (not ok)
    return same, other


def nearest_existing(path: Path) -> Path:
    folder = Path(path)
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    return folder


def choose_side_path(base: str, epoch: int) -> Tuple[Optional[Path], str]:
    parent, leaf = os.path.split(os.path.normpath(base))
    real_parent = os.path.realpath(parent)
    if not os.path.isdir(real_parent):
        return None, f"{parent} is not a folder here"
    stem = f"{leaf}-{target.crate_date(epoch)}"
    for n in range(1, MAX_CLASH + 1):
        name = stem if n == 1 else f"{stem}-{n}"
        if not os.path.lexists(os.path.join(real_parent, name)):
            return Path(real_parent) / name, ""
    return None, f"{MAX_CLASH} folders named {stem} already exist"


def _placed_files(records: List[FileRecord], side: Path, col: Collector) -> Tuple[List[Tuple[FileRecord, Path]], List[LinkPlan]]:
    files: List[Tuple[FileRecord, Path]] = []
    links: List[LinkPlan] = []
    link_rels = frozenset(r.rel for r in records if r.role == ROLE_PROJECT_LINK and safe_rel(r.rel))
    for record in sorted(records, key=lambda r: r.rel):
        if not safe_rel(record.rel):
            col.warn(W_PROJECT_FILE_KEPT, f"{record.rel[:80]}: not a plain relative path")
        elif record.role == ROLE_PROJECT_LINK:
            text = str(record.extra.get("link_target") or "")
            links.append(LinkPlan(record.rel, text, record, link_verdict(record.rel, text, link_rels)))
        else:
            files.append((record, side / record.rel))
    return files, links


def plan_side(reader: CrateReader, files: List[FileRecord], crate: target.CrateProject, decision: target.TargetDecision,
              request: ImportRequest, prov: Provenance, env: ImportEnv, col: Collector, fixed: Optional[str] = None) -> Optional[SidePlan]:
    records = project_records(files)
    if request.work_in_restored_copy and not (prov.own and request.include_project_files and records):
        col.block(B_BAD_REQUEST, "work_in_restored_copy needs an own crate that carries the project files, and include_project_files")
        return None
    if not request.include_project_files or not records:
        return None
    base = _base_root(crate, decision, request)
    root = str(decision.root_to) if decision.root_to else None
    matching = differing = 0
    if not fixed and root and os.path.isdir(root) and not os.path.islink(root):
        there_files, there_links = _placed_files(records, Path(root), Collector())
        matching, differing = compare_with_disk(there_files, there_links, Path(root))
        if matching and not differing:
            return SidePlan(Path(root), work_here=request.work_in_restored_copy, into_root=True, already_here=True, matching=matching)
    into_root = (str(fixed) == root) if fixed else root_is_free(root)
    if into_root and root:
        chosen, why = Path(root), ""
    else:
        chosen, why = (Path(fixed), "") if fixed else (choose_side_path(base, crate.created_epoch) if base else (None, "the crate names no project folder"))
    if chosen is None:
        col.block(B_ROOT_REFUSED, f"project files: {why}")
        return None
    problem = (target.sensitive_root_problem(str(chosen), str(env.user_home())) or target.protected_problem(str(chosen), env)
               or (None if prov.own or is_within(str(chosen), os.path.realpath(env.projects_dir))
                   else target.home_choice_problem(os.path.realpath(chosen), env)))
    if problem is not None:
        col.block(B_ROOT_REFUSED, f"{chosen} {problem}")
        return None
    out = SidePlan(chosen, work_here=request.work_in_restored_copy, into_root=bool(into_root and root), matching=matching, differing=differing)
    out.files, out.links = _placed_files(records, chosen, col)
    out.bytes = sum(r.length for r, _d in out.files)
    out.claude_config = sorted(r.rel for r, _d in out.files if _CONFIG.search(r.rel))
    git = reader.manifest.extra.get("project_git")
    out.git, out.patch = (git if isinstance(git, dict) else None), reader.has(M_PROJECT_PATCH)
    space_at = nearest_existing(chosen if out.into_root else chosen.parent)
    free = env.free_bytes(space_at)
    if not fixed and out.bytes * DISK_HEADROOM > free:
        col.block(B_NO_SPACE, f"project files need {out.bytes} bytes, {free} free at {space_at}")
    for link in out.links:
        if link.why:
            col.warn(W_LINK_NOT_CREATED, f"{link.rel}: {link.why}")
    return out


from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import structlog

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.stamp_memo import StampMemo
from src.cplugs.save.vault.manifest import HOME_CLAUDE, HOME_CODEX, ManifestError, check_unit, memory_unit_id

logger = structlog.get_logger()

FAMILY_CLAUDE, FAMILY_CODEX = "claude", "codex"
KIND_CONVERSATION, KIND_MEMORY, KIND_SIDE_DBS = "conversation", "memory", "side_databases"
_CODEX_ID_CHARS = 36
_CWD_RE = re.compile(rb'"cwd"\s*:\s*("(?:[^"\\]|\\.)*")')
_PEEK_BYTES = 256 * 1024
MEMORY_DIR = "memory"
MERGED_SIDE_PREFIX = "_from-"
_SIDECAR_DIRS = ("subagents", "tool-results", MEMORY_DIR)
MAX_NEST = 3
_LISTING = "listing"


@dataclass(frozen=True)
class Sources:

    claude_roots: Tuple[Path, ...]
    codex_home: Path
    state_dir: Path


@dataclass(frozen=True)
class PlannedFile:

    path: Path
    role: str
    home: str
    rel: str


@dataclass
class UnitPlan:

    unit: str
    kind: str
    family: str
    conversation_id: Optional[str] = None
    encoded_folder: Optional[str] = None
    files: List[PlannedFile] = field(default_factory=list)

    def main_path(self) -> Optional[Path]:
        return next((f.path for f in self.files if f.role in (K.ROLE_TRANSCRIPT, K.ROLE_CODEX_ROLLOUT)), None)


@dataclass(frozen=True)
class _Entry:

    name: str
    is_dir: bool
    is_file: bool


def _scan_listing(path: Path) -> Tuple[_Entry, ...]:
    with os.scandir(path) as scan:
        return tuple(sorted((_Entry(e.name, e.is_dir(follow_symlinks=False), e.is_file(follow_symlinks=False)) for e in scan),
                            key=lambda entry: entry.name))


def _list(path: Path, memo: Optional[StampMemo] = None) -> Tuple[_Entry, ...]:
    try:
        return memo.get(path, _LISTING, lambda: _scan_listing(path)) if memo is not None else _scan_listing(path)
    except OSError as exc:
        logger.warning("vault_folder_unreadable", path=str(path), error=str(exc))
        return ()


@dataclass(frozen=True)
class _TreeSpec:

    base: Path
    rel_prefix: str
    home: str
    role: Optional[str] = None


@dataclass(frozen=True)
class _Node:

    files: Tuple["PlannedFile", ...]
    dirs: Tuple[Path, ...]

    def __len__(self) -> int:
        return len(self.files) + len(self.dirs)


def _scan_node(spec: _TreeSpec, folder: Path) -> _Node:
    with os.scandir(folder) as scan:
        found = sorted(((e.name, e.is_symlink(), e.is_dir(follow_symlinks=False)) for e in scan), key=lambda item: item[0])
    inside = folder.relative_to(spec.base).as_posix()
    files: List[PlannedFile] = []
    dirs: List[Path] = []
    for name, is_link, is_dir in found:
        if is_link:
            logger.debug("vault_symlink_skipped", path=str(folder / name))
        elif is_dir:
            dirs.append(folder / name)
        else:
            inner = name if inside == "." else f"{inside}/{name}"
            role = spec.role or _role_in_folder(PurePosixPath(inner))
            files.append(PlannedFile(folder / name, role, spec.home, f"{spec.rel_prefix}/{inner}"))
    return _Node(tuple(files), tuple(dirs))


def _tree_files(spec: _TreeSpec, memo: Optional[StampMemo] = None) -> List["PlannedFile"]:
    planned: List[PlannedFile] = []
    pending = [spec.base]
    while pending:
        folder = pending.pop()
        try:
            node = memo.get(folder, spec, lambda: _scan_node(spec, folder)) if memo is not None else _scan_node(spec, folder)
        except OSError as exc:
            logger.warning("vault_walk_unreadable", path=str(folder), error=str(exc))
            continue
        planned.extend(node.files)
        pending.extend(reversed(node.dirs))
    return planned


def _role_in_folder(rel_in_folder: PurePosixPath) -> str:
    first = rel_in_folder.parts[0]
    if first == "subagents" and rel_in_folder.suffix == ".jsonl":
        return K.ROLE_SUBAGENT
    if first == "tool-results":
        return K.ROLE_TOOL_RESULT
    return K.ROLE_CONVERSATION_OTHER


def _conv_id(entry: _Entry) -> Optional[str]:
    if entry.name.startswith("."):
        return None
    if entry.is_file:
        if entry.name.endswith(".jsonl"):
            return entry.name[:-6] or None
        head, sep, tail = entry.name.partition(".jsonl.")
        return head if sep and head and tail else None
    return entry.name if entry.is_dir and entry.name != MEMORY_DIR and not _is_merged_side(entry) else None


def _is_merged_side(entry: _Entry) -> bool:
    return entry.is_dir and entry.name.startswith(MERGED_SIDE_PREFIX)


def _is_project_folder(name: str, entries: Sequence[_Entry]) -> bool:
    return name.startswith("-") or any((e.is_file and not e.name.startswith(".")) or (e.is_dir and e.name == MEMORY_DIR)
                                       or _is_merged_side(e) for e in entries)


class Scanner:

    def __init__(self, sources: Sources, memo: Optional[StampMemo] = None) -> None:
        self.sources = sources
        self._memo = memo
        self._listings: Dict[Path, Tuple[_Entry, ...]] = {}
        self._encs: Dict[Path, List[Tuple[str, Path]]] = {}
        self._index: Optional[Dict[str, List[Tuple[Path, str, Path]]]] = None
        self._codex: Optional[Dict[str, UnitPlan]] = None

    def listing(self, path: Path) -> Tuple[_Entry, ...]:
        if path not in self._listings:
            self._listings[path] = _list(path, self._memo)
        return self._listings[path]

    def encs(self, root: Path) -> List[Tuple[str, Path]]:
        if root not in self._encs:
            found: List[Tuple[str, Path]] = []

            def walk(folder: Path, prefix: str, depth: int) -> None:
                for entry in self.listing(folder):
                    if not entry.is_dir or entry.name.startswith(".") or entry.name in _SIDECAR_DIRS or entry.name.startswith(MERGED_SIDE_PREFIX):
                        continue
                    child = folder / entry.name
                    if _is_project_folder(entry.name, self.listing(child)):
                        found.append((prefix + entry.name, child))
                    elif depth + 1 < MAX_NEST:
                        walk(child, prefix + entry.name + "/", depth + 1)

            walk(root, "", 0)
            self._encs[root] = found
        return self._encs[root]

    def conv_index(self) -> Dict[str, List[Tuple[Path, str, Path]]]:
        if self._index is None:
            index: Dict[str, List[Tuple[Path, str, Path]]] = {}
            for root in self.sources.claude_roots:
                for enc, path in self.encs(Path(root)):
                    for conv in dict.fromkeys(c for c in map(_conv_id, self.listing(path)) if c):
                        index.setdefault(conv, []).append((Path(root), enc, path))
            self._index = index
        return self._index

    def plan_claude(self, conv: str) -> Optional[UnitPlan]:
        plan = UnitPlan(check_unit(conv), KIND_CONVERSATION, FAMILY_CLAUDE, conv)
        seen = set()
        for root in dict.fromkeys(Path(r) for r in self.sources.claude_roots):
            for found_root, enc, path in self.conv_index().get(conv, []):
                if found_root != root:
                    continue
                found = self._claude_files(root, enc, path, conv)
                if found:
                    plan.encoded_folder = plan.encoded_folder or enc
                    plan.files += [f for f in found if f.path not in seen]
                    seen.update(f.path for f in found)
            plan.files += [f for f in self._history_files(root, conv) if f.path not in seen]
        return plan if plan.files else None

    def _claude_files(self, root: Path, enc: str, enc_path: Path, conv: str) -> List[PlannedFile]:
        out: List[PlannedFile] = []
        for entry in self.listing(enc_path):
            if entry.is_file and entry.name == f"{conv}.jsonl":
                out.append(PlannedFile(enc_path / entry.name, K.ROLE_TRANSCRIPT, HOME_CLAUDE, f"projects/{enc}/{entry.name}"))
            elif entry.is_file and entry.name.startswith(f"{conv}.jsonl."):
                out.append(PlannedFile(enc_path / entry.name, K.ROLE_CONVERSATION_OTHER, HOME_CLAUDE, f"projects/{enc}/{entry.name}"))
            elif entry.is_dir and entry.name == conv:
                out += _tree_files(_TreeSpec(enc_path / conv, f"projects/{enc}/{conv}", HOME_CLAUDE), self._memo)
        return out

    def scan_claude(self, skipped: Optional[List[str]] = None) -> Dict[str, UnitPlan]:
        plans: Dict[str, UnitPlan] = {}
        for conv in self.conv_index():
            try:
                plan = self.plan_claude(conv)
            except ManifestError:
                logger.warning("vault_unsafe_conversation_name", name=conv)
                if skipped is not None:
                    skipped.append(conv)
                continue
            if plan is not None:
                plans[conv] = plan
        return plans

    def codex(self) -> Dict[str, UnitPlan]:
        if self._codex is None:
            plans: Dict[str, UnitPlan] = {}
            for rollout in self._rollouts():
                conv = rollout.path.stem[-_CODEX_ID_CHARS:]
                try:
                    check_unit(conv)
                except ManifestError:
                    logger.warning("vault_unsafe_rollout_name", name=rollout.path.name)
                    continue
                plans.setdefault(conv, UnitPlan(conv, KIND_CONVERSATION, FAMILY_CODEX, conv)).files.append(rollout)
            self._codex = plans
        return self._codex

    def _history_files(self, root: Path, conv: str) -> List[PlannedFile]:
        base = root.parent / "file-history" / conv
        if not base.is_dir():
            return []
        return _tree_files(_TreeSpec(base, f"file-history/{conv}", HOME_CLAUDE, K.ROLE_FILE_HISTORY), self._memo)

    def _rollouts(self) -> Iterator[PlannedFile]:
        for sub in ("sessions", "archived_sessions"):
            base = self.sources.codex_home / sub
            if base.is_dir():
                spec = _TreeSpec(base, sub, HOME_CODEX, K.ROLE_CODEX_ROLLOUT)
                yield from (f for f in _tree_files(spec, self._memo) if f.path.name.startswith("rollout-") and f.path.suffix == ".jsonl")

    def scan_memory(self) -> Dict[str, UnitPlan]:
        plans: Dict[str, UnitPlan] = {}
        for root in self.sources.claude_roots:
            for enc, enc_path in self.encs(Path(root)):
                entries = self.listing(enc_path)
                files = [PlannedFile(enc_path / e.name, K.ROLE_MEMORY, HOME_CLAUDE, f"projects/{enc}/{e.name}")
                         for e in entries if e.is_file and not e.name.startswith(".") and _conv_id(e) is None]
                if any(e.is_dir and e.name == MEMORY_DIR for e in entries):
                    files += _tree_files(_TreeSpec(enc_path / MEMORY_DIR, f"projects/{enc}/{MEMORY_DIR}", HOME_CLAUDE, K.ROLE_MEMORY), self._memo)
                for side in (e for e in entries if _is_merged_side(e)):
                    files += _tree_files(_TreeSpec(enc_path / side.name, f"projects/{enc}/{side.name}", HOME_CLAUDE, K.ROLE_MEMORY), self._memo)
                if files:
                    unit = memory_unit_id(enc)
                    plan = plans.setdefault(unit, UnitPlan(unit, KIND_MEMORY, FAMILY_CLAUDE, None, enc))
                    plan.files += files
        return plans


def plan_claude(sources: Sources, conv: str, scanner: Optional[Scanner] = None) -> Optional[UnitPlan]:
    return (scanner or Scanner(sources)).plan_claude(conv)


def scan_claude(sources: Sources, scanner: Optional[Scanner] = None, skipped: Optional[List[str]] = None) -> Dict[str, UnitPlan]:
    return (scanner or Scanner(sources)).scan_claude(skipped)


def scan_codex(sources: Sources, scanner: Optional[Scanner] = None) -> Dict[str, UnitPlan]:
    return (scanner or Scanner(sources)).codex()


def plan_codex(sources: Sources, conv: str, scanner: Optional[Scanner] = None) -> Optional[UnitPlan]:
    return scan_codex(sources, scanner).get(conv)


def scan_memory(sources: Sources, scanner: Optional[Scanner] = None) -> Dict[str, UnitPlan]:
    return (scanner or Scanner(sources)).scan_memory()


def scan_all(sources: Sources, scanner: Optional[Scanner] = None, skipped: Optional[List[str]] = None) -> Dict[str, UnitPlan]:
    scan = scanner or Scanner(sources)
    return {**scan.scan_claude(skipped), **scan.codex(), **scan.scan_memory()}


def plan_for(sources: Sources, unit: str, family: Optional[str] = None, scanner: Optional[Scanner] = None) -> Optional[UnitPlan]:
    scan = scanner or Scanner(sources)
    if unit.startswith(K.MEMORY_UNIT_PREFIX):
        return scan.scan_memory().get(unit)
    if family == FAMILY_CODEX:
        return scan.codex().get(unit)
    return scan.plan_claude(unit)


def working_dir_in(head: bytes) -> Optional[str]:
    match = _CWD_RE.search(head[:_PEEK_BYTES])
    if match is None:
        return None
    try:
        value = json.loads(match.group(1))
    except ValueError:
        return None
    return value if isinstance(value, str) and value else None


def peek_working_dir(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        with open(path, "rb") as handle:
            head = handle.read(_PEEK_BYTES)
    except OSError:
        return None
    return working_dir_in(head)

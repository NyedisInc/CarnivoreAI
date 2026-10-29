
from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import structlog

from src.core.inventory.claude_folders import FORM_FOLDER, FORM_MAIN, conversation_entries, entries, project_folders
from src.core.inventory.identity import SAFE_CONVERSATION
from src.core.inventory.locations import claude_homes, codex_home
from src.core.inventory.model import (DELETE, KEEP, KIND_DIR, KIND_FILE, KIND_LINES, REPORT, ROLE_KEY, ROLE_PATH, Artifact,
                                      FieldRef, SessionIdentity)

logger = structlog.get_logger()

# conversation id
REWRITE_PROJECTS = (FieldRef("projects/<ENC(cwd)>", ROLE_PATH), FieldRef("conversation id", ROLE_KEY))
REWRITE_BY_CONVERSATION = (FieldRef("conversation id", ROLE_KEY),)
REWRITE_CODEX = (FieldRef("cwd in the first record", ROLE_PATH), FieldRef("conversation id", ROLE_KEY))
EXTRA_COPY_REASON = ("a set-aside, conflict or archived copy of the conversation's files; an export carries it, a purge "
                     "reports it and leaves it")


def _inside(path: str, root: Path) -> bool:
    parent = os.path.realpath(os.path.dirname(path))
    real_root = os.path.realpath(str(root))
    return parent == real_root or parent.startswith(real_root + os.sep)


def _measure(path: str) -> Tuple[str, int, int]:
    if os.path.islink(path) or not os.path.isdir(path):
        return KIND_FILE, 1, os.lstat(path).st_size
    files = size = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            files += 1
            try:
                size += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
    return KIND_DIR, files, size


def measured_artifact(store: str, path: str, root: Path, action: str, reason: str, blockers: List[str],
                      rewrite: Sequence[FieldRef] = (), derived: bool = False) -> Optional[Artifact]:
    """One file or folder as an artifact, or a blocker when it resolves outside ``root``.

    Inputs: store (the label); path; root (the folder it must sit inside); action; reason; blockers (appended to);
      rewrite (what an importer rewrites); derived (an export rebuilds it).
    Output: Artifact | None. Example: measured_artifact("claude", "/h/projects/-a/x.jsonl", Path("/h/projects"), "delete", "", [])
    """
    if not _inside(path, root):
        blockers.append(f"{path} resolves outside {root}; refusing to touch it")
        return None
    try:
        kind, files, size = _measure(path)
    except OSError as exc:
        blockers.append(f"{path} could not be read: {type(exc).__name__}")
        return None
    return Artifact(store=store, kind=kind, what=path, count=files, size=size, action=action, reason=reason,
                    locator={"path": path, "root": str(root)}, rewrite=list(rewrite), derived=derived)


def _registry_records(home: Path, conv: str) -> List[str]:
    out: List[str] = []
    for path in sorted(glob.glob(str(home / "sessions" / "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            logger.debug("session_purge_registry_unreadable", path=path, error=type(exc).__name__)
            continue
        if isinstance(data, dict) and data.get("sessionId") == conv:
            out.append(path)
    return out


def _history_lines(home: Path, conv: str) -> int:
    path = home / "history.jsonl"
    needle = f'"{conv}"'
    count = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if needle in line:
                    count += 1
    except OSError:
        return 0
    return count


def _extra_copies(projects: Path, conv: str, listed: set) -> List[Tuple[str, Path, bool]]:
    out: List[Tuple[str, Path, bool]] = []
    top = {str(projects / e.name) for e in entries(projects)}
    for _rel, folder in project_folders(projects):
        nested = str(folder) not in top
        for path, form in conversation_entries(folder, conv):
            if (nested or form not in (FORM_MAIN, FORM_FOLDER)) and str(path) not in listed:
                out.append((str(path), projects, True))
    return out


def _claude_paths(home: Path, conv: str) -> List[Tuple[str, Path, bool]]:
    found: List[Tuple[str, Path, bool]] = []
    projects = home / "projects"
    for pattern in (f"*/{conv}.jsonl", f"*/{conv}"):
        found += [(p, projects, False) for p in sorted(glob.glob(str(projects / pattern)))]
    found += _extra_copies(projects, conv, {p for p, _, _ in found})
    todos = home / "todos"
    found += [(p, todos, False) for p in sorted(glob.glob(str(todos / f"{conv}-*.json")))]
    for sub in ("file-history", "session-env"):
        path = home / sub / conv
        if os.path.lexists(path):
            found.append((str(path), home / sub, False))
    debug = home / "debug" / f"{conv}.txt"
    if os.path.lexists(debug):
        found.append((str(debug), home / "debug", False))
    found += [(p, home / "sessions", False) for p in _registry_records(home, conv)]
    return found


def _conversation_artifacts(conv: str, homes: Sequence[Path], codex_root: Path, action: str, reason: str,
                            blockers: List[str], seen: set) -> List[Artifact]:
    arts: List[Artifact] = []
    for home in homes:
        for path, root, extra in _claude_paths(Path(home), conv):
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            rewrite = REWRITE_PROJECTS if root.name == "projects" else REWRITE_BY_CONVERSATION
            art = measured_artifact("claude", path, root, REPORT if extra else action, EXTRA_COPY_REASON if extra else reason,
                                    blockers, rewrite)
            if art is not None:
                arts.append(art)
        lines = _history_lines(Path(home), conv)
        if lines:
            arts.append(Artifact(store="claude", kind=KIND_LINES, what=str(Path(home) / "history.jsonl"), count=lines,
                                 action=REPORT, reason="Claude's prompt history holds every conversation in one "
                                 "file; its lines are counted, never rewritten",
                                 locator={"path": str(Path(home) / "history.jsonl"), "match": conv}))
    for sub, pattern in (("sessions", f"*/*/*/rollout-*-{conv}.jsonl"), ("archived_sessions", f"rollout-*-{conv}.jsonl")):
        for path in sorted(glob.glob(str(codex_root / sub / pattern))):
            art = measured_artifact("codex", path, codex_root / sub, action, reason, blockers, REWRITE_CODEX)
            if art is not None:
                arts.append(art)
    return arts + _codex_extras(conv, codex_root, blockers)


def _codex_extras(conv: str, codex_root: Path, blockers: List[str]) -> List[Artifact]:
    out: List[Artifact] = []
    snapshots = codex_root / "shell_snapshots"
    for path in sorted(glob.glob(str(snapshots / f"{conv}*.sh"))):
        art = measured_artifact("codex", path, snapshots, REPORT, "the shell environment the Codex thread ran in; recreated by a new thread",
                                blockers, REWRITE_CODEX[1:], derived=True)
        if art is not None:
            out.append(art)
    index = codex_root / "session_index.jsonl"
    lines = _index_lines(index, conv)
    if lines:
        out.append(Artifact(store="codex", kind=KIND_LINES, what=str(index), count=lines, action=REPORT,
                            reason="Codex's thread index holds every thread in one file; its lines are counted, never rewritten",
                            locator={"path": str(index), "match": conv}, rewrite=[FieldRef("id", ROLE_KEY)]))
    return out


def _index_lines(path: Path, conv: str) -> int:
    needle = f'"id":"{conv}"'
    count = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if needle in line.replace(' ', ''):
                    count += 1
    except OSError:
        return 0
    return count


def trace(ident: SessionIdentity, shared_reason: str = "", homes: Optional[Iterable[Path]] = None,
          codex: Optional[Path] = None, related: Iterable[str] = (), *,
          related_blockers: Optional[List[str]] = None) -> Tuple[List[Artifact], List[str]]:
    if not ident.conversation and not related:
        return [], []
    resolved = [Path(h) for h in homes] if homes is not None else claude_homes()
    codex_root = codex if codex is not None else codex_home()
    arts: List[Artifact] = []
    blockers: List[str] = []
    seen: set = set()
    if ident.conversation:
        arts += _conversation_artifacts(ident.conversation, resolved, codex_root, KEEP if shared_reason else DELETE,
                                        shared_reason, blockers, seen)
    for conv in related:
        if not SAFE_CONVERSATION.match(conv):
            logger.warning("inventory_unsafe_conversation_id", conversation=conv)
            continue
        skipped: List[str] = []
        arts += _conversation_artifacts(conv, resolved, codex_root, REPORT,
                                        "an earlier conversation of this session; a purge reports it and leaves it",
                                        skipped, seen)
        for sentence in skipped:
            logger.warning("inventory_related_file_not_traced", conversation=conv, problem=sentence)
        if related_blockers is not None:
            related_blockers.extend(skipped)
    return arts, blockers


def delete(art: Artifact) -> None:
    import shutil

    path, root = art.locator["path"], Path(art.locator["root"])
    if not _inside(path, root):
        raise ValueError(f"{path} now resolves outside {root}")
    if not os.path.lexists(path):
        return
    if os.path.islink(path) or not os.path.isdir(path):
        os.unlink(path)
    else:
        shutil.rmtree(path)

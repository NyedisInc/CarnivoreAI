
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import structlog

from src.core.claude_project_dirs import path_spellings
from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.project_move.icloud import read_text_if_local

logger = structlog.get_logger()

SETTINGS_FILES: Tuple[str, ...] = ("settings.json", "settings.local.json")

CLAUDE_JSON = ".claude.json"

NOT_READ_CLOUD_ONLY = "cloud-only in iCloud; not downloaded to read it"


def transcript_roots() -> Tuple[Path, ...]:
    from src.core.claude_config.transcript_roots import claude_transcript_roots

    return claude_transcript_roots()


def claude_json_files(config_path: Optional[Path] = None) -> List[Path]:
    from src.config import settings
    from src.core.claude_config.profile_roots import account_profile_dirs

    config = Path(config_path or settings.auth_config_file).expanduser()
    candidates = [Path.home() / CLAUDE_JSON]
    candidates += [profile / CLAUDE_JSON for profile in account_profile_dirs(config)]
    out: List[Path] = []
    seen: Set[str] = set()
    for path in candidates:
        if not path.is_file():
            continue
        real = os.path.realpath(path)
        if real not in seen:
            seen.add(real)
            out.append(path)
    return out


def files_under(folder: Path) -> List[str]:
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(folder):
        rel = os.path.relpath(dirpath, folder)
        links = [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
        for name in filenames + links:
            out.append(os.path.normpath(os.path.join(rel, name)))
    return sorted(out)


def _source_dirs(root: Path, old_path: str, target_name: str, claimed: Set[str],
                 conflicts: List[str]) -> List[Path]:
    sources: List[Path] = []
    for name in dict.fromkeys(slugify_project_dir(s) for s in path_spellings(old_path)):
        source = Path(root) / name
        if name == target_name or str(source) in claimed:
            continue
        try:
            if not source.is_dir():
                continue
        except OSError as exc:
            conflicts.append(f"transcript folder {source} could not be read: {exc}")
            continue
        claimed.add(str(source))
        sources.append(source)
    return sources


def transcript_moves(
    path_pairs: Sequence[Tuple[str, str]], roots: Iterable[Path], foreign_paths: Iterable[str]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    foreign = {slugify_project_dir(p) for p in foreign_paths if p}
    moves: List[Dict[str, Any]] = []
    conflicts: List[str] = []
    claimed: Set[str] = set()
    for root in roots:
        for old_path, new_path in path_pairs:
            target_name = slugify_project_dir(new_path)
            target = Path(root) / target_name
            spelling_of: Dict[str, str] = {}
            for spelling in path_spellings(old_path):
                spelling_of.setdefault(slugify_project_dir(spelling), spelling)
            own_target = target_name in spelling_of
            sources = _source_dirs(Path(root), old_path, target_name, claimed, conflicts)
            if not sources:
                continue
            conflicts.extend(f"transcript folder {s} is shared with a folder that is not moving"
                             for s in sources if s.name in foreign)
            if os.path.lexists(target) and not own_target:
                conflicts.append(f"transcript folder {target} already exists; merge it by hand first")
                continue
            if os.path.lexists(target):
                merge_from, held = sources, set(files_under(target))
            else:
                moves.append({"root": str(root), "from": str(sources[0]), "to": str(target), "mode": "rename",
                              "spelling": spelling_of[sources[0].name]})
                merge_from, held = sources[1:], set(files_under(sources[0]))
            for source in merge_from:
                files = files_under(source)
                clash = sorted(held.intersection(files))
                if clash:
                    conflicts.append(f"{source} and {target} both hold {', '.join(clash[:5])}"
                                     f"{' and more' if len(clash) > 5 else ''}; merge those by hand first")
                held.update(files)
                moves.append({"root": str(root), "from": str(source), "to": str(target), "mode": "merge",
                              "files": len(files), "spelling": spelling_of[source.name]})
    return moves, conflicts


def trust_keys(files: Iterable[Path], moved_paths: Iterable[str]) -> List[Dict[str, Any]]:
    spellings: Set[str] = set()
    for path in moved_paths:
        spellings.update(path_spellings(path))
    out: List[Dict[str, Any]] = []
    for file in files:
        try:
            text = read_text_if_local(Path(file))
            if text is None:
                out.append({"file": str(file), "error": NOT_READ_CLOUD_ONLY})
                continue
            data = json.loads(text)
        except (OSError, ValueError) as exc:
            logger.warning("project_move_claude_json_unreadable", file=str(file), error=type(exc).__name__)
            out.append({"file": str(file), "error": "unreadable"})
            continue
        projects = data.get("projects") if isinstance(data, dict) else None
        if isinstance(projects, dict):
            keys = sorted(k for k in projects if k in spellings)
            if keys:
                out.append({"file": str(file), "keys": keys})
    return out


def settings_mentions(bases: Iterable[str], old_root: str) -> List[Dict[str, Any]]:
    spellings = path_spellings(old_root)
    out: List[Dict[str, Any]] = []
    for base in bases:
        for name in SETTINGS_FILES:
            file = Path(base) / ".claude" / name
            try:
                text = read_text_if_local(file)
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as exc:
                logger.warning("project_move_settings_unreadable", file=str(file), error=type(exc).__name__)
                continue
            if text is None:
                out.append({"file": str(file), "not_read": NOT_READ_CLOUD_ONLY})
                continue
            hits = [s for s in spellings if s in text]
            if hits:
                out.append({"file": str(file), "spellings": hits})
    return out

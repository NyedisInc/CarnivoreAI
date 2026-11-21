
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import structlog

logger = structlog.get_logger()

CODE_DIR_NAME = "plugins"
LEGACY_CODE_DIR_NAME = "cplug-code"
DATA_DIR_NAME = "plugin-data"
LEGACY_DATA_PARENT = "cplugs"
UUID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

KIND_CODE = "code"
KIND_DATA = "data"


class LayoutMoveFailed(OSError):
    pass


@dataclass(frozen=True)
class Move:

    kind: str
    src: Path
    dst: Path
    files: int = 0
    bytes: int = 0

    def as_json(self) -> Dict[str, object]:
        return {"kind": self.kind, "src": str(self.src), "dst": str(self.dst), "files": self.files, "bytes": self.bytes}


def code_parent(state_dir: Path) -> Path:
    return Path(state_dir) / CODE_DIR_NAME


def legacy_code_parent(state_dir: Path) -> Path:
    return Path(state_dir) / LEGACY_CODE_DIR_NAME


def code_root(state_dir: Path, name: str) -> Path:
    new = code_parent(state_dir) / name
    old = legacy_code_parent(state_dir) / name
    return old if not os.path.lexists(new) and os.path.lexists(old) else new


def data_parent(state_dir: Path) -> Path:
    return Path(state_dir) / DATA_DIR_NAME


def data_root(state_dir: Path, key: str) -> Path:
    old = Path(state_dir) / LEGACY_DATA_PARENT / key
    if not UUID_PATTERN.match(key):
        return old
    new = data_parent(state_dir) / key
    return old if not os.path.lexists(new) and os.path.lexists(old) else new


def measure(folder: Path) -> Tuple[int, int]:
    files = size = 0
    for root, dirs, names in os.walk(folder, followlinks=False):
        for name in [*names, *(d for d in dirs if os.path.islink(os.path.join(root, d)))]:
            files += 1
            try:
                size += os.lstat(os.path.join(root, name)).st_size
            except OSError as exc:
                logger.debug("plugin_layout_measure_skipped", error_type=type(exc).__name__)
    return files, size


def _entry(kind: str, src: Path, dst: Path) -> Move:
    files, size = measure(src)
    return Move(kind, src, dst, files, size)


def plan_moves(state_dir: Path) -> List[Move]:
    state = Path(state_dir)
    moves: List[Move] = []
    old_code, new_code = legacy_code_parent(state), code_parent(state)
    if old_code.is_dir() and not old_code.is_symlink():
        if not os.path.lexists(new_code):
            moves.append(_entry(KIND_CODE, old_code, new_code))
        else:
            for child in sorted(old_code.iterdir()):
                target = new_code / child.name
                if os.path.lexists(target):
                    raise LayoutMoveFailed(f"{target}: already exists; {child} was not moved")
                moves.append(_entry(KIND_CODE, child, target))
    old_data = state / LEGACY_DATA_PARENT
    if old_data.is_dir():
        for child in sorted(old_data.iterdir()):
            if not (UUID_PATTERN.match(child.name) and child.is_dir() and not child.is_symlink()):
                continue
            target = data_parent(state) / child.name
            if os.path.lexists(target):
                raise LayoutMoveFailed(f"{target}: already exists; {child} was not moved")
            moves.append(_entry(KIND_DATA, child, target))
    return moves


def _same_volume(moves: Sequence[Move]) -> bool:
    for move in moves:
        parent = move.dst.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if os.stat(move.src).st_dev != os.stat(parent).st_dev:
            return False
    return True


def _undo(done: Sequence[Move]) -> List[str]:
    stuck: List[str] = []
    for move in reversed(done):
        try:
            os.rename(move.dst, move.src)
        except OSError as exc:
            logger.error("plugin_layout_undo_failed", src=str(move.src), dst=str(move.dst), error_type=type(exc).__name__)
            stuck.append(str(move.dst))
    return stuck


def _verify(move: Move) -> None:
    files, size = measure(move.dst)
    if (files, size) != (move.files, move.bytes):
        raise LayoutMoveFailed(f"{move.dst}: holds {files} files / {size} bytes after the move, {move.files} / {move.bytes} before")


def apply_moves(moves: Sequence[Move], journal: Path) -> None:
    if not moves:
        return
    if not _same_volume(moves):
        raise LayoutMoveFailed("the plugin folders and their new place are on different volumes; a move would copy, so nothing was moved")
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps({"moves": [m.as_json() for m in moves]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    done: List[Move] = []
    try:
        for move in moves:
            move.dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(move.src, move.dst)
            done.append(move)
            _verify(move)
    except (OSError, LayoutMoveFailed) as exc:
        stuck = _undo(done)
        suffix = f"; could not restore {stuck}" if stuck else ""
        raise LayoutMoveFailed(f"{type(exc).__name__}: {exc}{suffix}") from exc


def undo_moves(moves: Sequence[Move]) -> None:
    stuck = _undo(moves)
    if stuck:
        raise LayoutMoveFailed(f"could not restore {stuck}")


from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Tuple

import structlog

from src.plugins.save.offload import constants as C
from src.plugins.save.vault.units import PlannedFile

logger = structlog.get_logger()


class MoveRefused(RuntimeError):

    def __init__(self, code: str, detail: str, stuck: Sequence[str] = ()) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.stuck = list(stuck)


@dataclass(frozen=True)
class Moved:

    source: Path
    held: Path
    size: int
    mtime_ns: int


def holding_root(state_dir: Path) -> Path:
    return Path(state_dir) / C.HOLDING_DIRNAME


def holding_path(holding_root: Path, unit: str, planned: PlannedFile) -> Path:
    return Path(holding_root) / unit / planned.home / planned.rel


def _rename_back(moved: Sequence[Moved]) -> List[str]:
    stuck: List[str] = []
    for item in reversed(list(moved)):
        try:
            if os.path.lexists(item.source):
                stuck.append(str(item.source))
                continue
            os.rename(item.held, item.source)
        except OSError as exc:
            logger.error("offload_rollback_failed", held=str(item.held), source=str(item.source), error=str(exc))
            stuck.append(str(item.source))
    return stuck


def move_to_holding(files: Sequence[PlannedFile], holding_root: Path, unit: str, expected: Optional[Mapping[Path, Tuple[int, int]]] = None) -> Tuple[Moved, ...]:
    moved: List[Moved] = []
    try:
        for planned in files:
            held = holding_path(holding_root, unit, planned)
            info = os.lstat(planned.path)
            size, mtime_ns = expected.get(Path(planned.path), (-1, -1)) if expected is not None else (info.st_size, info.st_mtime_ns)
            if (info.st_size, info.st_mtime_ns) != (size, mtime_ns):
                raise MoveRefused(C.CODE_IN_USE, f"{planned.path.name} changed after it was verified: something still has it open")
            held.parent.mkdir(parents=True, exist_ok=True)
            if os.lstat(held.parent).st_dev != info.st_dev:
                raise MoveRefused(C.CODE_HOLDING_UNUSABLE, f"the holding folder is on another volume than {planned.path.parent}, so a move would copy")
            if os.path.lexists(held):
                raise MoveRefused(C.CODE_HOLDING_UNUSABLE, f"{held} is already held")
            os.rename(planned.path, held)
            moved.append(Moved(planned.path, held, size, mtime_ns))
        for item in moved:
            now = os.lstat(item.held)
            if (now.st_size, now.st_mtime_ns) != (item.size, item.mtime_ns):
                raise MoveRefused(C.CODE_IN_USE, f"{item.source.name} changed while it was moved: something still has it open")
    except MoveRefused as refused:
        refused.stuck = _rename_back(moved)
        if refused.stuck:
            logger.error("offload_move_stuck", unit=unit, stuck=refused.stuck)
        raise
    except OSError as exc:
        stuck = _rename_back(moved)
        raise MoveRefused(C.CODE_MOVE_FAILED, f"{exc.strerror or exc}; every file was put back" + (f" except {len(stuck)}" if stuck else ""), stuck) from exc
    return tuple(moved)


def move_back(moved: Sequence[Moved]) -> List[str]:
    return _rename_back(moved)

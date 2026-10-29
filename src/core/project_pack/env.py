
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Tuple

from src.core.project_pack import constants as K
from src.core.project_pack.trash import TrashFn, trash_paths


def _free_bytes(path: str) -> int:
    return shutil.disk_usage(path).free


def _transcript_roots() -> Tuple[Path, ...]:
    from src.core.project_move import claude_side

    return claude_side.transcript_roots()


@dataclass
class PackEnv:

    trash: TrashFn = trash_paths
    level: int = K.COMPRESSION_LEVEL
    free_bytes: Callable[[str], int] = _free_bytes
    margin: int = K.FREE_SPACE_MARGIN_BYTES
    transcript_roots: Callable[[], Iterable[Path]] = _transcript_roots
    state_dir: Path | None = None
    extra_forbidden: Tuple[str, ...] = field(default_factory=tuple)

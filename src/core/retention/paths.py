
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Set

from src.core.retention import constants as K


@dataclass(frozen=True)
class RetentionPaths:

    state_dir: Path
    rollback_dir: Path
    menubar_log_dir: Path
    drive_root: Path
    is_mount: Callable[[Path], bool] = os.path.ismount
    scratch_root: Optional[Path] = None
    live_sessions: Callable[[], Optional[Set[str]]] = lambda: None


def default_paths(state_dir: Path, home: Optional[Path] = None) -> RetentionPaths:
    base = home or Path.home()
    override = os.environ.get(K.ROLLBACK_ENV)
    rollback = Path(override).expanduser() if override else base.joinpath(*K.ROLLBACK_HOME_REL)
    from src.core.attention.registry_index import live_session_uuids

    return RetentionPaths(
        state_dir=state_dir,
        rollback_dir=rollback,
        menubar_log_dir=base.joinpath(*K.MENUBAR_LOG_HOME_REL),
        drive_root=Path(K.DRIVE_ROOT),
        scratch_root=Path(K.SCRATCH_ROOT_TEMPLATE.format(uid=os.getuid())),
        live_sessions=live_session_uuids,
    )

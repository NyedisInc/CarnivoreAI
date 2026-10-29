
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Tuple

import structlog

from src.core.safe_io.readonly_db import connect_readonly
from src.core.conversation_writers import MeasureError, Writer, live_writers, read_process_table
from src.core.project_move.plan import PaneListing

logger = structlog.get_logger()

DB_FILE = "carnivore.db"


class EnvUnreadable(RuntimeError):
    pass


def measure_writers() -> Optional[Tuple[Writer, ...]]:
    from src.core.claude_resume_argv import is_claude_command

    try:
        return tuple(live_writers(read_process_table(), is_claude_command))
    except MeasureError as exc:
        logger.warning("crate_import_writers_unmeasured", error=str(exc))
        return None


def free_bytes_of(path: Path) -> int:
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return int(shutil.disk_usage(probe).free)
    except OSError as exc:
        logger.warning("crate_import_free_space_unreadable", path=str(probe), error=str(exc))
        return 0


@dataclass(frozen=True)
class StoreHome:

    root: Path
    purge: str = ""
    default: bool = False


class BoardRelinkFailed(RuntimeError):
    pass


def no_plugin_homes(plugin_id: str, data_id: str) -> Optional[StoreHome]:
    return None


def registered_backup_sources() -> Sequence[Any]:
    from src.core.deepsearch.fallback_hook import sources

    return sources()


def all_plugins_enabled(plugin_id: str) -> bool:
    return True


def no_relink(slug: str, item_id: int) -> bool:
    return False


@dataclass(frozen=True)
class ImportEnv:

    state: Path
    projects_dir: str
    claude_homes: Tuple[Path, ...]
    codex_home: Path
    install_id: Optional[str]
    panes: Callable[[], PaneListing]
    writers: Callable[[], Optional[Tuple[Writer, ...]]] = measure_writers
    free_bytes: Callable[[Path], int] = free_bytes_of
    db_file: Optional[Path] = None
    receipts: Optional[Path] = None
    config_path: Optional[Path] = None
    theme_installed: Optional[Callable[[str], bool]] = None
    plugin_homes: Callable[[str, str], Optional[StoreHome]] = no_plugin_homes
    relink_board: Callable[[str, int], bool] = no_relink
    backup_sources: Callable[[], Sequence[Any]] = registered_backup_sources
    plugin_enabled: Callable[[str], bool] = all_plugins_enabled
    home: Optional[Path] = None

    def user_home(self) -> Path:
        return Path(self.home) if self.home else Path.home()

    def backup_dir(self, import_id: str) -> Path:
        base = Path(self.receipts) if self.receipts else Path(self.state) / "cplugs" / "crate" / "imports"
        return base / import_id / "backups"

    def claude_projects_root(self) -> Path:
        return Path(self.claude_homes[0]) / "projects"

    def protected_homes(self) -> Tuple[Path, ...]:
        return (*[Path(h) for h in self.claude_homes], Path(self.codex_home), Path(self.state))

    def connect(self) -> sqlite3.Connection:
        path = Path(self.db_file) if self.db_file else Path(self.state) / DB_FILE
        try:
            conn = connect_readonly(path)
        except sqlite3.Error as exc:
            raise EnvUnreadable(f"{path.name} cannot be opened: {exc}") from exc
        conn.row_factory = sqlite3.Row
        return conn

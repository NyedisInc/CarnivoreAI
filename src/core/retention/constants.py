
from __future__ import annotations

from typing import Final, Tuple

DRIVE_ROOT: Final[str] = "/Volumes/Backup"
DRIVE_MARKER_FILE: Final[str] = "README-FILING.md"
DRIVE_MARKER_DIR: Final[str] = "carnivore-installs"

DB_BACKUP_DRIVE_DIR: Final[Tuple[str, ...]] = ("manual-backups", "carnivore-db")
LOG_DRIVE_DIR: Final[Tuple[str, ...]] = ("manual-backups", "carnivore-menubar-logs")
APP_ARCHIVE_DRIVE_DIR: Final[Tuple[str, ...]] = ("carnivore-installs", "app-archive")
APP_EXPIRED_DRIVE_DIR: Final[Tuple[str, ...]] = ("carnivore-installs", "expired")

ROLLBACK_ENV: Final[str] = "CARNIVORE_ROLLBACK_DIR"
ROLLBACK_HOME_REL: Final[Tuple[str, ...]] = ("Library", "Application Support", "Carnivore-rollback")
ROLLBACK_PACKED_SUBDIR: Final[str] = "packed"
MENUBAR_LOG_HOME_REL: Final[Tuple[str, ...]] = ("Library", "Application Support", "Carnivore Menubar", "logs")

DEFAULT_KEEP_DB_BACKUPS: Final[int] = 2
DEFAULT_KEEP_ROLLBACK_BUNDLES: Final[int] = 2
DEFAULT_LOG_CAP_MB: Final[int] = 50
DEFAULT_INTERVAL_SECONDS: Final[int] = 86_400
STARTUP_DELAY_SECONDS: Final[int] = 120

PROTECTED_NAMES: Final[Tuple[str, ...]] = (
    "carnivore.db", "carnivore.online-backup.db", "vault", "checkpoints", "session-journal", "crates", "claude-code-local",
)

BUNDLE_SUFFIX: Final[str] = ".app"
ARCHIVE_SUFFIX: Final[str] = ".tar.zst"
PARTIAL_SUFFIX: Final[str] = ".partial"
COPY_CHUNK_BYTES: Final[int] = 4 * 1024 * 1024
FREE_SPACE_MARGIN_BYTES: Final[int] = 256 * 1024 * 1024
PACK_TIMEOUT_SECONDS: Final[int] = 3_600

LOG_ACTIVE_WINDOW_SECONDS: Final[int] = 600
LOG_ROTATED_PATTERN: Final[str] = r"\.(\d+|old|gz|zst)(\.(gz|zst))?$"
EXTRA_TOOL_DIRS: Final[Tuple[str, ...]] = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")

SCRATCH_ROOT_TEMPLATE: Final[str] = "/private/tmp/claude-{uid}"
SCRATCH_SUBDIR: Final[str] = "scratchpad"
DEFAULT_SCRATCH_IDLE_HOURS: Final[int] = 24

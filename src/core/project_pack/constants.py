
from __future__ import annotations

from typing import Tuple

STATE_UNPACKED = "unpacked"
STATE_PACKING = "packing"
STATE_VERIFYING = "verifying"
STATE_RETIRING = "retiring"
STATE_PACKED = "packed"
STATE_EXTRACTING = "extracting"
STATE_RESTORING = "restoring"

BUSY_STATES: Tuple[str, ...] = (STATE_PACKING, STATE_VERIFYING, STATE_RETIRING, STATE_EXTRACTING, STATE_RESTORING)
ALL_STATES: Tuple[str, ...] = (STATE_UNPACKED, STATE_PACKED) + BUSY_STATES

MANIFEST_NAME = ".carnivore-pack.json"
README_NAME = "PACKED-README.txt"
ARCHIVE_INFIX = ".packed-"
ARCHIVE_SUFFIX = ".tar.zst"
PARTIAL_SUFFIX = ".partial"
ORIGINALS_PREFIX = ".carnivore-originals-"
RESTORE_PREFIX = ".carnivore-restore-"

MANIFEST_FORMAT = 1

TAR_BIN = "/usr/bin/tar"
TRASH_BIN = "/usr/bin/trash"
NICE_BIN = "/usr/bin/nice"

COMPRESSION_LEVEL = 19
ZSTD_LONG_WINDOW = 27
NICE_LEVEL = 10

FREE_SPACE_MARGIN_BYTES = 2 * 1024 ** 3

HASH_CHUNK = 1024 * 1024

GIT_TIMEOUT_SECONDS = 30
GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}

GIT_SKIP_DIRS: Tuple[str, ...] = ("node_modules", ".venv", "venv", "site-packages", "__pycache__")

INCOMPRESSIBLE_SUFFIXES: Tuple[str, ...] = (
    ".zip", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".7z", ".rar", ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".heic", ".mp3", ".m4a", ".aac", ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".pdf", ".dmg", ".pkg", ".woff2",
)
ESTIMATE_RATIO_LOW = 0.20
ESTIMATE_RATIO_HIGH = 0.40

PROGRESS_NOTIFY_SECONDS = 3.0

LARGEST_FOLDERS = 5

TRANSCRIPT_KEY_PREFIX = "-"
TRANSCRIPT_SUFFIX = ".jsonl"

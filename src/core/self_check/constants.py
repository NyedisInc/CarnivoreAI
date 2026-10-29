
from __future__ import annotations

from typing import Tuple

PASS: str = "PASS"
FAIL: str = "FAIL"

CHECK_FILES: str = "files"
CHECK_SPACE: str = "space"
CHECK_TMUX: str = "tmux"
CHECK_CLAUDE_CLI: str = "claude_cli"
CHECK_ACCESS: str = "full_disk_access"
ALL_CHECKS: Tuple[str, ...] = (CHECK_FILES, CHECK_SPACE, CHECK_TMUX, CHECK_CLAUDE_CLI, CHECK_ACCESS)

INTERVAL_SECONDS: float = 10 * 60
COMMAND_TIMEOUT_SECONDS: float = 5.0

SF_DATALESS: int = 0x40000000
MAX_SAMPLE_STATS: int = 300

LOW_SPACE_FREE_BYTES: int = 5 * 1024 ** 3

ALERT_SOURCE: str = "self_check"
ALERT_KEY_PREFIX: str = "self_check."
TITLE_KEY: str = "app_alert.self_check.{check}.title"
DETAIL_KEY: str = "app_alert.self_check.{check}.detail"
MAX_FINDINGS_CHARS: int = 600

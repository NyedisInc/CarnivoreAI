
from __future__ import annotations

from typing import Tuple

HELPER_NAMES: Tuple[str, ...] = ("codex", "codex-code-mode-host", "codex-exec-server")
HOST_NAME: str = "codex-code-mode-host"

QUARANTINE_ATTR: str = "com.apple.quarantine"
XATTR_PATH: str = "/usr/bin/xattr"
FLAG_USER_APPROVED: int = 0x0040
XATTR_TIMEOUT_SECONDS: float = 2.0

HANDSHAKE_TIMEOUT_SECONDS: float = 5.0
REAP_TIMEOUT_SECONDS: float = 2.0
HELLO_MESSAGE: dict = {"type": "connection/hello", "supportedVersions": [1], "requiredCapabilities": [],
                       "optionalCapabilities": []}
READY_TYPE: str = "connection/ready"
MAX_REPLY_BYTES: int = 64 * 1024

HS_READY: str = "ready"
HS_TIMEOUT: str = "timeout"
HS_EXITED: str = "exited"
HS_BAD_REPLY: str = "bad_reply"
HS_SPAWN_FAILED: str = "spawn_failed"

OK: str = "ok"
BLOCKED: str = "blocked"
HOST_FAILED: str = "host_failed"
NOT_APPLICABLE: str = "not_applicable"
VERDICTS: Tuple[str, ...] = (OK, BLOCKED, HOST_FAILED, NOT_APPLICABLE)
FAILING: Tuple[str, ...] = (BLOCKED, HOST_FAILED)

ALERT_SOURCE: str = "self_check"
ALERT_KEY_PREFIX: str = "self_check.codex_helpers."
TITLE_KEYS = {BLOCKED: "app_alert.self_check.codex_helpers.blocked.title", HOST_FAILED: "app_alert.self_check.codex_helpers.host_failed.title"}
DETAIL_KEYS = {BLOCKED: "app_alert.self_check.codex_helpers.blocked.detail", HOST_FAILED: "app_alert.self_check.codex_helpers.host_failed.detail"}
NOTIFY_VARIANTS = {BLOCKED: "codex_helpers_blocked", HOST_FAILED: "codex_helpers_host_failed"}
ROW_KEYS = {BLOCKED: "codex_helpers.row.blocked", HOST_FAILED: "codex_helpers.row.host_failed"}

LAUNCH_WAIT_SECONDS: float = HANDSHAKE_TIMEOUT_SECONDS + 3.0
NOTICE_REASON: str = "codex_helpers"

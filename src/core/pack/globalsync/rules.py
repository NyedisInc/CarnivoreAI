
from __future__ import annotations

import fnmatch
import re
from typing import Optional, Tuple

HARNESSES: Tuple[str, ...] = ("claude", "codex", "agy")
ONLY_ITEMS = {"agents": ("skills",), "agy": ("skills", "rules")}
HOME_TOKEN = "@@CARNIVORE-HOME@@"

DENIED_NAMES: frozenset = frozenset({
    "projects", "sessions", "archived_sessions", "session_index.jsonl", "todos", "tasks", "teams", "file-history", "shell-snapshots",
    "shell_snapshots", "session-env", "ide", "statsig", "paste-cache", "uploads", "plans", "jobs", "agent-questions", "replays",
    "thread_history backup", "tui-thread-reference-capabilities", "generated_images", "visualizations", "feedback", "dictation-history",
    "cache", "debug", "logs", "log", "telemetry", "downloads", "backups", "tmp", "temp", "daemon", "state", "stats-cache.json",
    "models_cache.json", "version.json", "installation_id", "ipc", "node_repl", "packages", "browser", "chrome", "computer-use",
    "sqlite", "app-server-control", "app-server-daemon", "project-metadata-locks", "thread-writer-locks", "mcp-oauth-locks",
    "rollout-migrations", "ambient-suggestions", "vendor_imports", "pets",
    "auth.json", "policy-limits.json", "remote-settings.json", "mcp-needs-auth-cache.json", "chrome-native-hosts-v2.json",
    "claude-cowork-import-history.json", "external_agent_session_imports.json", "transcription-history.jsonl", "history.jsonl",
    "mcp-optin", "carnivore-mcp.json", "carnivore-mcp-migration.json",
})
DENIED_GLOBS: Tuple[str, ...] = ("*.sqlite*", "*.db", "*.db-*", "*.lock", "*.lock.*", "*.log", "*.pid", "*.sock", "history*", "*-bak-*",
                                 "*.synced-at", "*.stamp.json", "*.signature.json", "carnivore-*", ".*", "*credentials*", "*.jsonl")
PLUGIN_FILES: Tuple[str, ...] = ("plugins/installed_plugins.json", "plugins/known_marketplaces.json", "plugins/blocklist.json")
PLUGIN_DIRS: Tuple[str, ...] = ("plugins/marketplaces", "plugins/cache")
SLOT_RE = re.compile(r"^(claude|codex|agents|agy)\.(default|[a-z0-9][a-z0-9._-]{0,62})$")

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FILES = 60000
MAX_DEPTH = 14
MAX_PATH_BYTES = 1024
MAX_NAME_BYTES = 255
MAX_REFUSALS_KEPT = 50

MACHINE_LOCAL_NAMES = frozenset({"node_modules", ".venv", "venv", "__pycache__", ".git", ".trash", ".carnivore-trash"})
RECEIVER_OWNED_NAMES = frozenset({"openai-bundled"})
RECEIVER_OWNED_GLOBS: Tuple[str, ...] = ("temp_git_*",)
IGNORED_BASENAMES = frozenset({".DS_Store", ".carnivore-skill.json"})
SCRUBBED_NAMES = frozenset({"settings.json", "config.toml", ".mcp.json"})

REASON_LINK = "link"
REASON_TOO_LARGE = "too large"
REASON_BACKUP_FILE = "backup file"
REASON_BUDGET = "over the size budget"


def is_machine_local(name: str) -> bool:
    return name in MACHINE_LOCAL_NAMES or name in RECEIVER_OWNED_NAMES or any(fnmatch.fnmatchcase(name, g) for g in RECEIVER_OWNED_GLOBS)


def is_litter(name: str) -> bool:
    return name in IGNORED_BASENAMES or ".bak" in name or name.endswith("~") or name.endswith(".swp")


def is_denied(name: str) -> bool:
    return name in DENIED_NAMES or any(fnmatch.fnmatchcase(name, g) for g in DENIED_GLOBS)


def path_problem(kind: str, rel: str) -> Optional[str]:
    if not rel or len(rel.encode("utf-8", "replace")) > MAX_PATH_BYTES or "\x00" in rel or rel.startswith("/") or "\\" in rel:
        return "bad path"
    parts = rel.split("/")
    if len(parts) > MAX_DEPTH or any(p in ("", ".", "..") or len(p.encode("utf-8", "replace")) > MAX_NAME_BYTES for p in parts):
        return "bad path"
    if any(is_machine_local(p) or is_litter(p) for p in parts):
        return "machine-local name"
    if parts[0] == "plugins" and kind == "claude":
        joined = "/".join(parts)
        return None if any(joined == a or joined.startswith(a + "/") for a in (*PLUGIN_FILES, *PLUGIN_DIRS)) else "not a synced item"
    if kind in ONLY_ITEMS and parts[0] not in ONLY_ITEMS[kind]:
        return "not a synced item"
    return "denied" if is_denied(parts[0]) else None

from __future__ import annotations


ALLOWED_TOP_LEVEL_FILES = frozenset({
    "CLAUDE.md",
    "CONFIGURATION_NOTES.md",
    "settings.json",
    "settings.local.json",
    ".credentials.json",
})

ALLOWED_TOP_LEVEL_DIRS = frozenset({
    "hooks",
    "rules",
    "commands",
    "skills",
    "agents",
    "scheduled-tasks",
    "scripts",
    "_scripts",
    "superclaude",
})

READONLY_COLLAPSED_DIRS = frozenset({"plugins"})

BLOCKLIST_ONLY_ROOTS = frozenset({"workdir"})

HIDE_NAMES = frozenset({
    "projects",
    "backups",
    "cache",
    "debug",
    "paste-cache",
    "session-env",
    "statsig",
    "todos",
    "shell-snapshots",
    "file-history",
    "history.jsonl",
    "stats-cache.json",
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    "__pycache__",
})

HIDE_PREFIXES = ()

SENSITIVE_NAMES = frozenset({
    ".credentials.json",
    "id_rsa",
    "id_ed25519",
})
SENSITIVE_PREFIXES = (".env",)
SENSITIVE_SUFFIXES = (".pem", ".key")

EXECUTABLE_EXTENSIONS = frozenset({".py", ".cjs", ".js", ".sh"})
EXECUTABLE_DIRS = frozenset({"hooks", "scripts"})

MAX_READ_BYTES = 2 * 1024 * 1024

TREE_MAX_DEPTH = 6

MAX_DIR_ENTRIES = 2000
MORE_MARKER_KIND = "more"

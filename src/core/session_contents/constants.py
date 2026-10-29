
from __future__ import annotations

from typing import Tuple

SCOPE_GLOBAL = "global"
SCOPE_PROJECT = "project"
SCOPE_PLUGIN = "plugin"

KIND_INSTRUCTIONS = "instructions"
KIND_SKILLS = "skills"
KIND_AGENTS = "agents"
KIND_COMMANDS = "commands"
KIND_HOOKS = "hooks"
KIND_OUTPUT_STYLES = "output_styles"
KIND_SETTINGS = "settings"
KIND_MCP = "mcp"
KIND_PLUGINS = "plugins"
KIND_PROMPTS = "prompts"
KIND_PROFILES = "profiles"

STATUS_LOADED = "loaded"
STATUS_AVAILABLE = "available"
STATUS_DISABLED = "disabled"

FAMILY_CLAUDE = "claude"
FAMILY_CODEX = "codex"

SECTIONS_BY_FAMILY = {
    FAMILY_CLAUDE: (KIND_INSTRUCTIONS, KIND_SKILLS, KIND_AGENTS, KIND_COMMANDS, KIND_HOOKS, KIND_OUTPUT_STYLES,
                    KIND_SETTINGS, KIND_MCP, KIND_PLUGINS),
    FAMILY_CODEX: (KIND_INSTRUCTIONS, KIND_SKILLS, KIND_PROMPTS, KIND_SETTINGS, KIND_PROFILES, KIND_MCP),
}

MAX_ITEMS_PER_SECTION = 300
MAX_ANCESTORS = 16
MAX_IMPORT_DEPTH = 5
MAX_READ_BYTES = 8 * 1024 * 1024
MAX_KEYS_SHOWN = 12

CLAUDE_JSON = ".claude.json"
PROJECT_MCP_FILE = ".mcp.json"
CLAUDE_MANAGED_DIRS: Tuple[str, ...] = ("/Library/Application Support/ClaudeCode", "/etc/claude-code")

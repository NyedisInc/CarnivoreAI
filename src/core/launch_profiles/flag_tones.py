
from __future__ import annotations

from typing import Dict, FrozenSet, Iterable, List, Literal, Optional, Tuple

from src.config.launch_profiles import PERMISSION_FIELD_FLAGS

Tone = Literal["safe", "danger", "unknown"]
SAFE: Tone = "safe"
DANGER: Tone = "danger"
UNKNOWN: Tone = "unknown"

Arity = Literal["none", "required", "optional"]

_CLAUDE_SAFE = frozenset({
    "-c", "-d", "-h", "-p", "-v", "-w", "--append-system-prompt", "--autocompact", "--ax-screen-reader", "--bg",
    "--background", "--bare", "--betas", "--brief", "--debug", "--debug-file", "--disable-slash-commands",
    "--disallowedTools", "--disallowed-tools", "--effort", "--exclude-dynamic-system-prompt-sections", "--file",
    "--forward-subagent-text", "--help", "--ide", "--include-hook-events", "--include-partial-messages",
    "--input-format", "--json-schema", "--max-budget-usd", "--no-chrome", "--no-session-persistence",
    "--output-format", "--print", "--prompt-suggestions", "--replay-user-messages", "--restricted", "--safe-mode",
    "--strict-mcp-config", "--system-prompt", "--system-prompt-snapshot", "--tmux", "--verbose", "--version",
    "--worktree",
})
_CLAUDE_DANGER = frozenset({
    "--add-dir", "--agent", "--agents", "--allowedTools", "--allowed-tools", "--chrome", "--cloud", "--desktop",
    "--environment", "--from-pr", "--mcp-config", "--permission-prompts", "--permission-prompt-tool", "--plugin-dir",
    "--plugin-url", "--remote-control", "--remote-control-session-name-prefix", "--setting-sources", "--settings",
    "--teleport", "--tools",
})
_CODEX_SAFE = frozenset({
    "-h", "-i", "-V", "--help", "--image", "--no-alt-screen", "--no-daemon", "--strict-config", "--version",
    "--worktree",
})
_CODEX_DANGER = frozenset({
    "-a", "-C", "-p", "-s", "--add-dir", "--approve-for-me", "--ask-for-approval", "--cd",
    "--dangerously-bypass-hook-trust", "--disable", "--enable",
    "--profile", "--remote", "--remote-auth-token-env", "--sandbox", "--search",
})
END_OF_OPTIONS = "--"

_CONFIG_OPTIONS = frozenset({"-c", "--config"})

_CLAUDE_REQUIRED = frozenset({
    "--add-dir", "--agent", "--agents", "--allowed-tools", "--allowedTools", "--append-system-prompt", "--autocompact",
    "--betas", "--debug-file", "--disallowed-tools", "--disallowedTools", "--effort", "--environment", "--file",
    "--input-format", "--json-schema", "--max-budget-usd", "--mcp-config", "--output-format", "--permission-mode",
    "--permission-prompts",
    "--permission-prompt-tool", "--plugin-dir", "--plugin-url", "--remote-control-session-name-prefix",
    "--setting-sources", "--settings", "--system-prompt", "--system-prompt-snapshot", "--tools",
})
_CLAUDE_OPTIONAL = frozenset({
    "-d", "-w", "--cloud", "--debug", "--from-pr", "--prompt-suggestions", "--remote-control", "--teleport", "--worktree",
})
_CODEX_REQUIRED = frozenset({
    "-a", "-C", "-c", "-i", "-p", "-s", "--add-dir", "--ask-for-approval", "--cd", "--config", "--disable", "--enable",
    "--image", "--profile", "--remote", "--remote-auth-token-env", "--sandbox",
})

_TABLES: Dict[str, Tuple[FrozenSet[str], FrozenSet[str], FrozenSet[str], FrozenSet[str]]] = {
    "claude": (_CLAUDE_SAFE, _CLAUDE_DANGER, _CLAUDE_REQUIRED, _CLAUDE_OPTIONAL),
    "codex": (_CODEX_SAFE, _CODEX_DANGER | _CONFIG_OPTIONS, _CODEX_REQUIRED, frozenset()),
}
_NO_TABLE: Tuple[FrozenSet[str], FrozenSet[str], FrozenSet[str], FrozenSet[str]] = (
    frozenset(), frozenset(), frozenset(), frozenset())

_TRUST_PREFIXES = ("approval", "sandbox", "permission")
_DANGER_KEYS = frozenset({
    "profile", "profiles", "notify", "mcp_servers", "model_provider", "model_providers", "shell_environment_policy",
})
_SAFE_KEYS = frozenset({
    "model_reasoning_effort", "model_reasoning_summary", "model_verbosity", "hide_agent_reasoning",
    "show_raw_agent_reasoning", "file_opener", "tui",
})


def known_options(harness: str) -> FrozenSet[str]:
    safe, danger, _required, _optional = _TABLES.get(harness, _NO_TABLE)
    return safe | danger | PERMISSION_FIELD_FLAGS


def option_arity(harness: str, name: str) -> Optional[Arity]:
    if name not in known_options(harness):
        return None
    _safe, _danger, required, optional = _TABLES.get(harness, _NO_TABLE)
    return "required" if name in required else "optional" if name in optional else "none"


def _config_tone(setting: str) -> Tone:
    key, _, value = setting.partition("=")
    segments = [seg.strip().strip("\"'") for seg in key.split(".")]
    if any(seg.startswith(_TRUST_PREFIXES) or seg in _DANGER_KEYS for seg in segments):
        return DANGER
    scalar = not value.strip().startswith(("{", "["))
    return SAFE if segments[0] in _SAFE_KEYS and scalar else UNKNOWN


def _option_tone(harness: str, option: str, value: str) -> Tone:
    safe, danger, _required, _optional = _TABLES.get(harness, _NO_TABLE)
    name, has_eq, glued = option.partition("=")
    if not option.startswith("--") and len(name) > 2:
        name, glued, has_eq = option[:2], option[2:], "="
    if name in PERMISSION_FIELD_FLAGS:
        return DANGER
    if harness == "codex" and name in _CONFIG_OPTIONS:
        return _config_tone(glued if has_eq else value)
    if name in danger:
        return DANGER
    return SAFE if name in safe else UNKNOWN


def _option_name(option: str) -> str:
    name = option.split("=", 1)[0]
    return name[:2] if not option.startswith("--") and len(name) > 2 else name


def _takes_next(harness: str, option: str) -> bool:
    if "=" in option or (not option.startswith("--") and len(option) > 2):
        return False
    return option_arity(harness, _option_name(option)) != "none"


def flag_groups(harness: str, flags: Iterable[str]) -> List[Tuple[str, Tone]]:
    groups: List[Tuple[str, Tone]] = []
    open_option: Optional[str] = None
    options_ended = False
    for token in flags:
        if options_ended or token == END_OF_OPTIONS:
            options_ended = True
            groups.append((token, DANGER))
        elif token.startswith("-"):
            groups.append((token, _option_tone(harness, token, "")))
            open_option = token if _takes_next(harness, token) else None
        elif open_option is not None:
            groups[-1] = (f"{open_option} {token}", _option_tone(harness, open_option, token))
            open_option = None
        else:
            groups.append((token, DANGER))
    return groups


from __future__ import annotations

import subprocess
from typing import Callable, Dict, List, Optional

import structlog

from src.core.agent_families import DEFAULT_FAMILY
from src.core.agent_wrappers import derive_accepts_model
from src.core.slash_command_labels import (
    MIGRATION_APPENDED_COMMANDS,
    append_missing_commands,
)

logger = structlog.get_logger()

COMMON_SLASH_COMMANDS_KEY = "common_slash_commands"

_SEED_SCRIPT_CLD = 'keyc "$@"'
_SEED_SCRIPT_CLDOR = 'clxor "$@"'


def probe_shell_function(
    name: str, runner: Optional[Callable[[List[str]], subprocess.CompletedProcess]] = None
) -> bool:
    run = runner or (
        lambda argv: subprocess.run(argv, capture_output=True, timeout=10)
    )
    try:
        result = run(["zsh", "-ic", f"type {name}"])
        return result.returncode == 0
    except Exception as e:
        logger.warning("probe_shell_function_failed", name=name, error=str(e))
        return False


def build_seed_wrappers(has_cld: bool, has_cldor: bool) -> List[Dict]:
    wrappers: List[Dict] = [
        {
            "id": "claude",
            "family": DEFAULT_FAMILY,
            "label": "claude",
            "script": 'command claude --dangerously-skip-permissions "$@"',
            "entry": None,
            "description": "plain Claude Code CLI, no wrapper",
            "default": not has_cld,
            "accepts_model": False,
        }
    ]
    if has_cld:
        wrappers.append(
            {
                "id": "keyc",
                "family": DEFAULT_FAMILY,
                "label": "keyc (subscription)",
                "script": _SEED_SCRIPT_CLD,
                "entry": None,
                "description": (
                    "forwards to the keyc shell function already defined in "
                    "~/.zshrc (subscription OAuth via macOS Keychain)"
                ),
                "default": True,
                "accepts_model": False,
            }
        )
    if has_cldor:
        wrappers.append(
            {
                "id": "clxor",
                "family": DEFAULT_FAMILY,
                "label": "clxor (openrouter)",
                "script": _SEED_SCRIPT_CLDOR,
                "entry": None,
                "description": (
                    "forwards to the clxor shell function already defined in "
                    "~/.zshrc (OpenRouter-routed, model as first argument)"
                ),
                "default": False,
                "accepts_model": True,
            }
        )
    return wrappers


def _step_v0_to_v1(data: Dict, has_cld: bool, has_cldor: bool) -> Optional[Dict]:
    agents_block = data.get("agents")
    if agents_block is None:
        agents_block = {}
    if not isinstance(agents_block, dict):
        logger.warning(
            "config_migration_skipped_bad_agents_block",
            raw_type=type(agents_block).__name__,
        )
        return None

    existing_claude_command = agents_block.get("claude_command", "")
    if existing_claude_command and str(existing_claude_command).strip():
        new_data = dict(data)
        new_data["agents"] = dict(agents_block)
        logger.info(
            "config_migration_version_stamped_no_wrappers",
            reason="explicit_claude_command_present",
        )
        return new_data

    if agents_block.get("wrappers"):
        new_data = dict(data)
        new_data["agents"] = dict(agents_block)
        return new_data

    seed = build_seed_wrappers(has_cld, has_cldor)
    new_agents_block = dict(agents_block)
    new_agents_block["wrappers"] = seed

    new_data = dict(data)
    new_data["agents"] = new_agents_block
    logger.info(
        "config_migration_seeded_wrappers",
        wrapper_ids=[w["id"] for w in seed],
        has_cld=has_cld,
        has_cldor=has_cldor,
    )
    return new_data


def _step_v1_to_v2(data: Dict) -> Dict:
    new_data = dict(data)

    agents_block = new_data.get("agents")
    if isinstance(agents_block, dict):
        wrappers = agents_block.get("wrappers")
        if isinstance(wrappers, list):
            annotated: List[Dict] = []
            for wrapper in wrappers:
                if not isinstance(wrapper, dict):
                    annotated.append(wrapper)
                    continue
                new_wrapper = dict(wrapper)
                if "accepts_model" not in new_wrapper:
                    new_wrapper["accepts_model"] = derive_accepts_model(new_wrapper)
                annotated.append(new_wrapper)
            new_agents_block = dict(agents_block)
            new_agents_block["wrappers"] = annotated
            new_data["agents"] = new_agents_block

    return new_data


def _step_v2_to_v3(data: Dict) -> Dict:
    new_data = dict(data)

    agents_block = new_data.get("agents")
    if not isinstance(agents_block, dict):
        return new_data

    wrappers = agents_block.get("wrappers")
    if not isinstance(wrappers, list):
        return new_data

    annotated: List[Dict] = []
    for wrapper in wrappers:
        if not isinstance(wrapper, dict) or "family" in wrapper:
            annotated.append(wrapper)
            continue
        new_wrapper = dict(wrapper)
        new_wrapper["family"] = DEFAULT_FAMILY
        annotated.append(new_wrapper)

    new_agents_block = dict(agents_block)
    new_agents_block["wrappers"] = annotated
    new_data["agents"] = new_agents_block
    return new_data


def _step_v3_to_v4(data: Dict) -> Dict:
    new_data = dict(data)

    raw = new_data.get(COMMON_SLASH_COMMANDS_KEY)
    if not isinstance(raw, list):
        return new_data

    new_data[COMMON_SLASH_COMMANDS_KEY] = append_missing_commands(
        raw, MIGRATION_APPENDED_COMMANDS
    )
    return new_data

def _step_v4_to_v5(data: Dict) -> Dict:
    new_data = dict(data)
    agents = new_data.get("agents")
    if not isinstance(agents, dict):
        return new_data
    wrappers = agents.get("wrappers")
    if not isinstance(wrappers, list):
        return new_data

    repaired = []
    changed = False
    for w in wrappers:
        if not isinstance(w, dict):
            repaired.append(w)
            continue
        script = w.get("script")
        if w.get("entry") or not isinstance(script, str) or not script.strip():
            repaired.append(w)
            continue
        if any(tok in script for tok in ('"$@"', "$@", "$1", "$*")):
            repaired.append(w)
            continue
        lines = script.rstrip().split("\n")
        last = lines[-1].rstrip()
        if "claude" not in last or last.lstrip().startswith("#"):
            repaired.append(w)
            continue
        lines[-1] = last + ' "$@"'
        fixed = dict(w)
        fixed["script"] = "\n".join(lines)
        repaired.append(fixed)
        changed = True

    if not changed:
        return new_data
    new_agents = dict(agents)
    new_agents["wrappers"] = repaired
    new_data["agents"] = new_agents
    return new_data

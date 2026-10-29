
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.config.launch_profiles import LaunchProfile
from src.core.launch_profiles.resolve import LaunchRequest, default_profile, pick_profile
from src.core.launch_profiles.store import LaunchProfileError, LaunchProfileStore, StaleRevision
from src.core.swarm import settings as swarm_settings
from src.core.swarm.definition import UPPER_RANKS

logger = structlog.get_logger()

SWARM_UPPER_ID = "swarm-upper"
ASK_POSTURE = "ask"
_REPO_SETTINGS = (".claude/settings.json", ".claude/settings.local.json")
_EDIT_RULE = re.compile(r"^(Edit|Write|MultiEdit|NotebookEdit)(\(|$)")
_READ_ONLY_MCP_RULES = frozenset({
    "mcp__filesystem__read_file", "mcp__filesystem__read_text_file", "mcp__filesystem__read_media_file",
    "mcp__filesystem__read_multiple_files", "mcp__filesystem__list_directory",
    "mcp__filesystem__list_directory_with_sizes", "mcp__filesystem__directory_tree",
    "mcp__filesystem__search_files", "mcp__filesystem__get_file_info", "mcp__filesystem__list_allowed_directories",
    "mcp__context7__resolve-library-id", "mcp__context7__get-library-docs", "mcp__context7__query-docs",
    "mcp__brave-search__brave_web_search", "mcp__brave-search__brave_local_search",
})


def upper_posture(config_path: Path) -> str:
    try:
        doc = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        doc = {}
    except (OSError, ValueError) as exc:
        raise LaunchProfileError("config.json cannot be read, so the upper-rank posture is unknown") from exc
    return swarm_settings.read_block(doc if isinstance(doc, dict) else {}).upper_ranks_permissions


def _seed_profile(posture: str) -> LaunchProfile:
    return LaunchProfile.model_validate({
        "id": SWARM_UPPER_ID, "harness": "claude", "label": "Swarm upper ranks",
        "description": "Launch profile of SysOp, company and project agents; its permissions follow the Swarm setting.",
        "permissions": posture, "model": {"mode": "fixed", "value": "opus"},
    })


def ensure_seed(config_path: Path, posture: str) -> bool:
    store = LaunchProfileStore(config_path)
    for _ in range(2):
        block = store.read()
        current = next((p for p in block.profiles if p.id == SWARM_UPPER_ID), None)
        if current is not None and current.permissions == posture:
            return False
        try:
            revision = block.revision
            if current is not None:
                store.put(current.model_copy(update={"permissions": posture}), expected_revision=revision)
                logger.info("swarm_upper_posture_synced", posture=posture)
                return True
            if not any(p.harness == "claude" for p in block.profiles):
                revision = store.put(default_profile([], "claude"), expected_revision=revision).revision
            store.put(_seed_profile(posture), expected_revision=revision)
        except StaleRevision:
            continue
        logger.info("swarm_upper_profile_seeded", posture=posture)
        return True
    raise LaunchProfileError("the launch profile store kept changing while seeding swarm-upper")


def sync_posture() -> None:
    from src.config import settings as app_settings

    path = Path(app_settings.auth_config_file).expanduser()
    try:
        if ensure_seed(path, upper_posture(path)):
            app_settings.drop_auth_config_cache()
    except (LaunchProfileError, OSError) as exc:
        logger.warning("swarm_upper_posture_sync_failed", error_type=type(exc).__name__, error=str(exc)[:200])


class ProfileRefused(ValueError):
    pass


def require_known(name: str) -> str:
    from src.config import settings as app_settings

    try:
        known = {p.id for p in LaunchProfileStore(Path(app_settings.auth_config_file).expanduser()).list()}
    except LaunchProfileError as exc:
        raise ProfileRefused("the launch profiles cannot be read") from exc
    if name.lower() not in known:
        raise ProfileRefused(f"no launch profile {name!r}; see launch_profiles_list")
    return name.lower()


def effective_profile(agent: Dict[str, Any]) -> Optional[str]:
    if agent.get("launch_profile"):
        return str(agent["launch_profile"])
    return SWARM_UPPER_ID if agent["rank"] in UPPER_RANKS and agent["harness"] == "claude" else None


def repo_settings_refusal(repo_dir: str) -> Optional[str]:
    for rel in _REPO_SETTINGS:
        path = Path(repo_dir) / rel
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            logger.warning("swarm_repo_settings_unreadable", path=str(path), error=type(exc).__name__)
            return f"its repo settings file {path} cannot be read or parsed, so what it pre-approves is unknown"
        perms = doc.get("permissions", {}) if isinstance(doc, dict) else None
        allow = perms.get("allow", []) if isinstance(perms, dict) else None
        if not isinstance(allow, list) or not all(isinstance(r, str) for r in allow):
            return f"its repo settings file {path} has a permissions block this check cannot read"
        for rule in allow:
            carnivore = rule == "mcp__carnivore" or rule.startswith("mcp__carnivore__")
            foreign_mcp = rule.startswith("mcp__") and not carnivore and rule not in _READ_ONLY_MCP_RULES
            if _EDIT_RULE.match(rule) or foreign_mcp:
                return f"its repo settings file {path} allows {rule!r}, which the upper-rank lockdown keeps behind a prompt"
    return None


def posture_refusal(agent: Dict[str, Any], config_path: Path, launched_as: Optional[str] = None) -> Optional[str]:
    if agent["rank"] not in UPPER_RANKS:
        return None
    try:
        posture = upper_posture(config_path)
        ensure_seed(config_path, posture)
        profile_id = launched_as or effective_profile(agent) or agent["harness"]
        picked = pick_profile(LaunchRequest(profiles=tuple(LaunchProfileStore(config_path).list()), agent_type=profile_id))
    except LaunchProfileError as exc:
        logger.warning("swarm_posture_unreadable", error=str(exc)[:200])
        return "its launch profiles cannot be read, so its permissions posture cannot be checked"
    if picked.permissions != posture:
        return f"its launch profile {picked.id!r} has permissions posture {picked.permissions!r}, not {posture!r}"
    return repo_settings_refusal(agent["repo_dir"]) if posture == ASK_POSTURE else None

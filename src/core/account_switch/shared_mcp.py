
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

import structlog

from src.config.mcp_launch import CLAUDE_MCP_CONFIG_FLAG
from src.core import config_writer

logger = structlog.get_logger()

SHARED_MCP_PATH_ENV_VAR = "CLOUDE_SHARED_MCP_PATH"

SHARED_MCP_FILENAME = "carnivore-mcp.json"

RECORD_FILENAME = "carnivore-mcp-migration.json"

MCP_KEY = "mcpServers"

FILE_MODE = 0o600

PROFILES_KEY = "profiles"
KEPT_KEY = "kept"


def shared_mcp_path() -> Path:
    override = os.environ.get(SHARED_MCP_PATH_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path(os.path.expanduser("~")) / ".claude" / SHARED_MCP_FILENAME


def record_path() -> Path:
    return shared_mcp_path().with_name(RECORD_FILENAME)


def read_servers(path: Path) -> Optional[Dict[str, Any]]:
    try:
        document = config_writer.read_config(path)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.warning("shared_mcp_unreadable", error=type(exc).__name__)
        return None
    servers = document.get(MCP_KEY) if isinstance(document, dict) else None
    return servers if isinstance(servers, dict) else None


def mcp_config_args() -> List[str]:
    path = shared_mcp_path()
    if read_servers(path) is None:
        return []
    return [f"{CLAUDE_MCP_CONFIG_FLAG}={path}"]


def is_copy(name: str, entry: Any, *sources: Mapping[str, Any]) -> bool:
    return any(name in source and source[name] == entry for source in sources)


def _read_record(path: Path) -> Dict[str, Set[str]]:
    try:
        document = config_writer.read_config(path)
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.warning("shared_mcp_record_unreadable", error=type(exc).__name__)
        return {}
    profiles = document.get(PROFILES_KEY) if isinstance(document, dict) else None
    if not isinstance(profiles, dict):
        return {}
    return {
        pid: {str(n) for n in (entry.get(KEPT_KEY) or [])}
        for pid, entry in profiles.items()
        if isinstance(entry, dict)
    }


def _commit(path: Path, mutate) -> Optional[Dict[str, Any]]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        config_writer.create_if_absent(path, mutate({}) or {}, file_mode=FILE_MODE)
        outcome = config_writer.commit(path, mutate, file_mode=FILE_MODE, external_writer=True)
    except (OSError, ValueError) as exc:
        logger.warning("shared_mcp_write_failed", file=path.name, error=type(exc).__name__)
        return None
    if outcome.status == config_writer.STALE_REVISION:
        logger.info("shared_mcp_write_raced", file=path.name)
        return None
    return outcome.data


def sync(
    default_servers: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
    *,
    shared_path: Optional[Path] = None,
    record: Optional[Path] = None,
) -> Tuple[Dict[str, Any], Dict[str, Set[str]]]:
    shared_path = shared_path or shared_mcp_path()
    record = record or record_path()
    shared = read_servers(shared_path) or {}
    kept = _read_record(record)

    new = {
        pid: sorted(n for n, entry in servers.items()
                    if not is_copy(n, entry, default_servers, shared))
        for pid, servers in profiles.items() if pid not in kept
    }
    if new:
        def add_profiles(document: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            current = document.get(PROFILES_KEY)
            current = dict(current) if isinstance(current, dict) else {}
            missing = {pid: {KEPT_KEY: names} for pid, names in new.items() if pid not in current}
            if not missing:
                return None
            return {**document, PROFILES_KEY: {**current, **missing}}

        if _commit(record, add_profiles) is not None:
            kept = _read_record(record)
            logger.info("shared_mcp_profiles_migrated", profiles=len(new),
                        kept=sum(len(n) for n in new.values()))

    wanted: Dict[str, Any] = {n: e for n, e in default_servers.items() if n not in shared}
    moved = 0
    for pid in sorted(profiles):
        if pid not in kept or pid in new:
            continue
        for name, entry in profiles[pid].items():
            if name not in shared and name not in wanted and name not in kept[pid]:
                wanted[name] = entry
                moved += 1
    if wanted or not shared_path.exists():
        def add_servers(document: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            own = document.get(MCP_KEY)
            own = dict(own) if isinstance(own, dict) else {}
            missing = {n: e for n, e in wanted.items() if n not in own}
            if not missing and isinstance(document.get(MCP_KEY), dict):
                return None
            return {**document, MCP_KEY: {**own, **missing}}

        written = _commit(shared_path, add_servers)
        if written is not None and wanted:
            logger.info("shared_mcp_synced", added_from_default=len(wanted) - moved,
                        moved_from_profiles=moved)
        shared = read_servers(shared_path) or {}
    return shared, kept


def default_servers(document: Any) -> Dict[str, Any]:
    servers = document.get(MCP_KEY) if isinstance(document, dict) else None
    return servers if isinstance(servers, dict) else {}


def strip_copies(
    servers: Mapping[str, Any], shared: Mapping[str, Any], kept: Iterable[str]
) -> Tuple[Dict[str, Any], int]:
    keep = set(kept)
    remaining = {
        n: e for n, e in servers.items() if n in keep or not is_copy(n, e, shared)
    }
    return remaining, len(servers) - len(remaining)


__all__ = [
    "FILE_MODE",
    "MCP_KEY",
    "RECORD_FILENAME",
    "SHARED_MCP_FILENAME",
    "SHARED_MCP_PATH_ENV_VAR",
    "default_servers",
    "is_copy",
    "mcp_config_args",
    "read_servers",
    "record_path",
    "shared_mcp_path",
    "strip_copies",
    "sync",
]

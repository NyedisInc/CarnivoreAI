
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

ROOTS_TTL_SECONDS = 15.0

SESSIONS_DIRNAME = "sessions"
PROJECTS_DIRNAME = "projects"
ALLOWED_SUBDIRS: FrozenSet[str] = frozenset({SESSIONS_DIRNAME, PROJECTS_DIRNAME})

_lock = threading.Lock()
_cache: Dict[Tuple[str, str, str], Tuple[float, Tuple[Path, ...]]] = {}


class ForbiddenSubdirError(ValueError):
    pass


def account_profile_dirs(config_path: Path) -> List[Path]:
    from src.config.provider_accounts import profile_dir_for
    from src.core.provider_ledger import accounts_store

    try:
        accounts = accounts_store.list_accounts(config_path)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.debug("profile_roots_config_unreadable", error=str(exc))
        return []
    out: List[Path] = []
    for account in accounts:
        if account.provider != "claude":
            continue
        profile = profile_dir_for(account)
        if profile:
            out.append(Path(os.path.expanduser(profile)))
    out.extend(_relay_profile_dirs())
    return out


ACCOUNTS_DIR_ENV = "CARNIVORE_ACCOUNTS_DIR"


def _relay_profile_dirs() -> List[Path]:
    override = os.environ.get(ACCOUNTS_DIR_ENV, "").strip()
    root = Path(override).expanduser() if override else Path.home() / ".carnivore" / "accounts"
    try:
        return sorted(p for p in root.glob("????????????-*-relay") if p.is_dir())
    except OSError:
        return []


def _default_config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file)


def profile_subdir_roots(
    default: Path, dirname: str, config_path: Optional[Path] = None
) -> Tuple[Path, ...]:
    if dirname not in ALLOWED_SUBDIRS:
        raise ForbiddenSubdirError("profile subdirectory not allowed: %r" % dirname)
    config = Path(config_path or _default_config_path()).expanduser()
    key = (str(config), str(default), dirname)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < ROOTS_TTL_SECONDS:
            return hit[1]
    roots: List[Path] = [Path(default)]
    seen = {os.path.realpath(default)}
    for profile in account_profile_dirs(config):
        candidate = profile / dirname
        try:
            if not candidate.is_dir():
                continue
        except OSError:
            continue
        real = os.path.realpath(candidate)
        if real in seen:
            continue
        seen.add(real)
        roots.append(candidate)
    result = tuple(roots)
    with _lock:
        _cache[key] = (now, result)
    return result


def claude_registry_roots(config_path: Optional[Path] = None) -> Tuple[Path, ...]:
    from src.core.attention import registry_index

    return profile_subdir_roots(
        Path(registry_index.default_registry_directory()), SESSIONS_DIRNAME, config_path
    )


def registry_file_path(pid: int) -> str:
    name = "%d.json" % pid
    roots = claude_registry_roots()
    for root in roots:
        candidate = root / name
        if candidate.is_file():
            return str(candidate)
    return str(roots[0] / name)


def reset_profile_roots_cache_for_tests() -> None:
    with _lock:
        _cache.clear()


from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple



PRODUCT_NAME = "Carnivore"

TMUX_SOCKET_NAME = "carnivore"
LEGACY_TMUX_SOCKET_NAMES: Tuple[str, ...] = ("cloude",)

TMUX_SESSION_PREFIX = "carnivore_"
LEGACY_TMUX_SESSION_PREFIXES: Tuple[str, ...] = ("cloude_",)

DB_FILENAME = "carnivore.db"
LEGACY_DB_FILENAMES: Tuple[str, ...] = ("cloude.db",)

DB_BACKUP_PREFIX = "carnivore.db.bak-v"
LEGACY_DB_BACKUP_PREFIXES: Tuple[str, ...] = ("cloude.db.bak-v",)

# state directory
STATE_DIR_NAME = "Carnivore"
LEGACY_STATE_DIR_NAMES: Tuple[str, ...] = ("CloudeCode",)

MENUBAR_STATE_DIR_NAME = "Carnivore Menubar"
LEGACY_MENUBAR_STATE_DIR_NAMES: Tuple[str, ...] = ("cloude-code-menubar",)

BUNDLE_ID = "ai.carnivore.menubar"
LEGACY_BUNDLE_IDS: Tuple[str, ...] = ("com.cloudecode.menubar",)

ENV_PREFIX = "CARNIVORE_"
LEGACY_ENV_PREFIXES: Tuple[str, ...] = ("CLOUDE_", "CLOUDECODE_")

UPLOAD_DIR_NAME = ".carnivore_uploads"
LEGACY_UPLOAD_DIR_NAMES: Tuple[str, ...] = (".cloude_uploads",)

# own project

BROWSER_KEY_PREFIX = "carnivore."
LEGACY_BROWSER_KEY_PREFIXES: Tuple[str, ...] = ("cloude.",)

RELEASE_REPO = "NyedisInc/CarnivoreAI"
LEGACY_RELEASE_REPOS: Tuple[str, ...] = ("NyedisInc/CarnivoreAI",)

LEGACY_MANAGED_HOOKS_MARKER = "# cloudecode-managed"




def is_owned_session_name(tmux_name: str) -> bool:
    if tmux_name.startswith(TMUX_SESSION_PREFIX):
        return True
    return any(tmux_name.startswith(prefix) for prefix in LEGACY_TMUX_SESSION_PREFIXES)


def strip_session_prefix(tmux_name: str) -> Optional[str]:
    if tmux_name.startswith(TMUX_SESSION_PREFIX):
        return tmux_name[len(TMUX_SESSION_PREFIX):]
    for prefix in LEGACY_TMUX_SESSION_PREFIXES:
        if tmux_name.startswith(prefix):
            return tmux_name[len(prefix):]
    return None


def sockets_to_probe(configured: Optional[str]) -> Tuple[str, ...]:
    if configured:
        return (configured,)
    return (TMUX_SOCKET_NAME, *LEGACY_TMUX_SOCKET_NAMES)


@dataclass(frozen=True)
class Resolution:

    path: Path
    used_legacy: bool
    both_present: bool


def resolve_named(parent: Path, current: str, legacy: Tuple[str, ...]) -> Resolution:
    current_path = parent / current
    legacy_paths = [parent / name for name in legacy]

    current_exists = current_path.exists()
    existing_legacy = [p for p in legacy_paths if p.exists()]

    if current_exists:
        return Resolution(
            path=current_path,
            used_legacy=False,
            both_present=bool(existing_legacy),
        )

    if existing_legacy:
        return Resolution(
            path=existing_legacy[0],
            used_legacy=True,
            both_present=False,
        )

    return Resolution(path=current_path, used_legacy=False, both_present=False)


def env_names(suffix: str) -> Tuple[str, ...]:
    return (f"{ENV_PREFIX}{suffix}",) + tuple(
        f"{prefix}{suffix}" for prefix in LEGACY_ENV_PREFIXES
    )


def env_value(suffix: str) -> Optional[str]:
    for name in env_names(suffix):
        if name in os.environ:
            return os.environ[name]
    return None


def identity_report() -> dict:
    return {
        "tmux_socket": "current",
        "session_prefix": "current",
        "db_filename": "current",
        "state_dir": "current",
        "menubar_state_dir": "current",
        "bundle_id": "current",
        "env_prefix": "current",
        "upload_dir": "current",
        "browser_key_prefix": "current",
        "release_repo": "current",
    }

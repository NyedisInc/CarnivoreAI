
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

import structlog

from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core.account_switch import session_pin
from src.core.crate_format.model import CrateManifest
from src.core.crate_format.reader import CrateReader
from src.core.crate_import import entries_in
from src.core.crate_import.env import ImportEnv

logger = structlog.get_logger()
_PIN_PREFIX = "session_account_pins."


def pins_in_crate(reader: CrateReader) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for entry in entries_in.records(reader):
        key = str(entry.get("key", ""))
        if entry.get("store") == entries_in.ACCOUNT_PINS and key.startswith(_PIN_PREFIX) and isinstance(entry.get("value"), str):
            out[key[len(_PIN_PREFIX):]] = entry["value"]
    return out


def conversation_homes(reader: CrateReader, manifest: CrateManifest, env: ImportEnv, *, own: bool) -> Dict[str, Path]:
    if not own or env.config_path is None:
        return {}
    pins = pins_in_crate(reader)
    if not pins:
        return {}
    try:
        accounts = {a.id: a for a in session_pin.all_accounts(env.config_path) if a.provider == session_pin.PIN_PROVIDER}
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("crate_import_accounts_unreadable", error=type(exc).__name__)
        return {}
    known = {os.path.realpath(h): Path(h) for h in env.claude_homes[1:]}
    default = os.path.realpath(env.claude_homes[0])
    out: Dict[str, Path] = {}
    for record in manifest.conversations:
        account = accounts.get(pins.get(record.session_uuid or "", ""))
        home = _profile_home(account, default, known)
        if home is not None:
            out[record.id] = home
    return out


def _profile_home(account: Optional[ProviderAccount], default_real: str, known: Dict[str, Path]) -> Optional[Path]:
    if account is None:
        return None
    real = os.path.realpath(os.path.expanduser(profile_dir_for(account)))
    return known.get(real) if real != default_real else None

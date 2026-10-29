
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from src.core.backup_health.vault_record import OPT_OUT_SETTING, SAVE_PLUGIN_ID, opt_out_units
from src.cplugs.host import state as owner_state
from src.cplugs.sdk.data_decl import DataDecl, default_store_root


@dataclass(frozen=True)
class VaultFolder:

    unit: str
    plugin_id: str
    data_id: str
    root: Optional[Path]
    opted_out: bool = False


def setting_root(state_dir: Path, value: Any, default: str) -> Optional[Path]:
    chosen = value.strip() if isinstance(value, str) else ""
    if chosen:
        return Path(chosen).expanduser()
    return default_store_root(state_dir, default) if default else None


def decl_root(state_dir: Path, plugin_id: str, decl: DataDecl, settings: Mapping[str, Any]) -> Optional[Path]:
    if decl.state_path:
        return Path(state_dir) / decl.state_path
    if decl.path:
        return Path(state_dir) / owner_state.STATE_DIR_NAME / plugin_id / decl.path
    root = setting_root(state_dir, settings.get(decl.root_setting), decl.default)
    return root / decl.sub if root is not None and decl.sub else root


def stored_settings(state_dir: Path, plugin_id: str) -> Optional[Dict[str, Any]]:
    entry = owner_state.stored_entry(state_dir, plugin_id)
    if entry is None:
        return None
    settings = entry.get("settings")
    return dict(settings) if isinstance(settings, dict) else {}


def vault_folders(state_dir: Path) -> List[VaultFolder]:
    from src.cplugs.host import runtime  # noqa: PLC0415

    out: List[VaultFolder] = []
    switched_off = opt_out_units((stored_settings(state_dir, SAVE_PLUGIN_ID) or {}).get(OPT_OUT_SETTING))
    for d in runtime.definitions():
        wanted = [decl for decl in d.manifest.data or () if decl.wants_vault]
        if not wanted or not owner_state.get(state_dir, d.manifest).enabled:
            continue
        settings = stored_settings(state_dir, d.id) or {}
        for decl in wanted:
            unit = decl.full_id(d.id)
            out.append(VaultFolder(unit, d.id, decl.id, decl_root(state_dir, d.id, decl, settings), opted_out=unit in switched_off))
    return out

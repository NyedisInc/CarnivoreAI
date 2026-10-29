
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import structlog

from src.config.config_file import read_config
from src.core import config_writer
from src.core.approvals.auto_answer.catalog import SCOPES
from src.core.approvals.beast_grid import cell_defaults
from src.cplugs.host import state as plugin_state

logger = structlog.get_logger()

PLUGIN_ID = "beastmode"
RETIRED_ID = "autoanswer"
AUTOANSWER_SWITCHES: Tuple[str, ...] = ("devChannels", "folderTrust", "externalImports", "chromeDecline")


def autoanswer_to_grid(old: Mapping[str, Any], was_on: bool = True) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in AUTOANSWER_SWITCHES:
        if not was_on:
            out[f"{key}Off"] = out[f"{key}On"] = False
        elif isinstance(old.get(key), bool):
            out[f"{key}Off"] = old[key]
            out[f"{key}On"] = old[key]
    if "trustScope" in old:
        out["trustScope"] = old["trustScope"]
    return out


def stored_grid(state_dir: Path) -> Tuple[Dict[str, bool], Optional[str]]:
    entry = plugin_state.stored_entry(state_dir, PLUGIN_ID)
    if entry is not None:
        raw = entry.get("settings") if isinstance(entry.get("settings"), dict) else {}
        was_on = entry.get("enabled") is not False
    else:
        old = plugin_state.stored_entry(state_dir, RETIRED_ID)
        if old is None:
            return {}, None
        was_on = old.get("enabled") is True
        raw = autoanswer_to_grid(old.get("settings") if isinstance(old.get("settings"), dict) else {}, was_on)
        was_on = True
    known = cell_defaults()
    cells = {key: value for key, value in raw.items() if key in known and isinstance(value, bool)}
    if not was_on:
        cells = {key: False for key in known}
    scope = raw.get("trustScope")
    return cells, (scope if scope in SCOPES else None)


def migrate(state_dir: Path, config_path: Path) -> bool:
    try:
        if "beast_grid" in (read_config(config_path).get("mcp") or {}):
            return False
        cells, scope = stored_grid(state_dir)

        def mutate(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            block = doc.get("mcp")
            block = dict(block) if isinstance(block, dict) else {}
            if "beast_grid" in block:
                return None
            block["beast_grid"] = cells
            if scope is not None:
                block["beast_trust_scope"] = scope
            return {**doc, "mcp": block}

        wrote = config_writer.commit(config_path, mutate).wrote
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.error("beast_grid_migration_failed", error_type=type(exc).__name__)
        return False
    if wrote:
        logger.info("beast_grid_migrated", cells=len(cells), scope=scope)
    return wrote

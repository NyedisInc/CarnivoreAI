
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Dict

import structlog

from src.cplugs.host import state as owner_state
from src.cplugs.sdk.data_decl import default_store_root
from src.cplugs.sdk.manifest import Manifest

logger = structlog.get_logger()

FILLED_STORES = (("reviewboard", "boards"),)


def blank_defaults(state_dir: Path, manifest: Manifest, settings: Dict[str, object]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for decl in manifest.data or ():
        if (manifest.id, decl.id) in FILLED_STORES and decl.root_setting and decl.default and not decl.sub:
            value = settings.get(decl.root_setting)
            if not (isinstance(value, str) and value.strip()):
                out[decl.root_setting] = str(default_store_root(state_dir, decl.default))
    return out


def fill(state_dir: Path, manifest: Manifest) -> Dict[str, str]:
    if not manifest.data:
        return {}
    wanted = blank_defaults(state_dir, manifest, owner_state.get(state_dir, manifest).settings)
    if not wanted:
        return {}
    stored: Dict[str, str] = {}

    def mutate(st: owner_state.CplugState) -> owner_state.CplugState:
        stored.clear()
        stored.update(blank_defaults(state_dir, manifest, st.settings))
        return replace(st, settings={**st.settings, **stored}) if stored else st

    try:
        owner_state.update(state_dir, manifest, None, mutate)
    except owner_state.StateWriteFailed:
        logger.error("cplug_default_root_not_stored", cplug=manifest.id)
        return {}
    if stored:
        logger.info("cplug_default_root_stored", cplug=manifest.id, settings=sorted(stored))
    return dict(stored)

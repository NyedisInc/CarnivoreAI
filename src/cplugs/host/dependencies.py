"""What a plugin needs and who needs it (``docs/cplugs.md`` 16, Task Manager 414).

Three kinds of need, with three strengths:

* ``min_app_version`` and ``requires_core`` REFUSE turning the plugin on (:func:`enable_blockers`, route 409
  ``requirements_unmet``): the app cannot run it at all.
* ``requires`` (other plugins) is a WARNING when one is off (shown on the plugins page, enforced at run time by
  ``gate.py``); it never refuses an enable.
* Turning a plugin OFF while other enabled plugins need it answers 409 ``has_dependents`` with their ids until the
  caller confirms (:func:`enabled_dependents`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.cplugs.host import runtime, state as owner_state
from src.cplugs.sdk import core_features
from src.cplugs.sdk.manifest import Manifest, version_tuple

logger = structlog.get_logger()


def app_version() -> str:
    from src.core import version  # noqa: PLC0415

    return version.startup_version()


def version_unmet(manifest: Manifest, have: str) -> Optional[Dict[str, str]]:
    if not have:
        logger.warning("cplug_app_version_unknown", cplug=manifest.id, need=manifest.min_app_version)
        return None
    try:
        too_old = version_tuple(have) < version_tuple(manifest.min_app_version)
    except ValueError:
        logger.warning("cplug_app_version_unparsed", cplug=manifest.id, have=have)
        return None
    return {"need": manifest.min_app_version, "have": have} if too_old else None


def enable_blockers(manifest: Manifest) -> Dict[str, Any]:
    blockers: Dict[str, Any] = {}
    unmet = version_unmet(manifest, app_version())
    if unmet:
        blockers["min_app_version"] = unmet
    missing = [c for c in manifest.requires_core if not core_features.available(c)]
    if missing:
        blockers["core"] = missing
    return blockers


def enabled_dependents(cplug_id: str, state_dir: Path) -> List[str]:
    defs = runtime.definitions()
    needs = {d.id: set(d.manifest.requires) for d in defs}
    reaches = {cplug_id}
    grew = True
    while grew:
        grew = False
        for pid, req in needs.items():
            if pid not in reaches and req & reaches:
                reaches.add(pid)
                grew = True
    reaches.discard(cplug_id)
    return [d.id for d in defs if d.id in reaches and owner_state.get(state_dir, d.manifest).enabled]


def dependency_view(manifest: Manifest, state_dir: Path) -> Dict[str, Any]:
    defs = {d.id: d for d in runtime.definitions()}

    def plugin_status(pid: str) -> str:
        d = defs.get(pid)
        if d is None:
            return "missing"
        return "on" if owner_state.get(state_dir, d.manifest).enabled else "off"

    have = app_version()
    return {
        "plugins": [{"id": pid, "status": plugin_status(pid)} for pid in manifest.requires],
        "core": [{"id": cid, "available": core_features.available(cid)} for cid in manifest.requires_core],
        "min_app_version": {"need": manifest.min_app_version, "have": have, "met": version_unmet(manifest, have) is None},
        "needed_by": [{"id": d.id, "enabled": owner_state.get(state_dir, d.manifest).enabled}
                      for d in defs.values() if manifest.id in d.manifest.requires and not runtime.hidden(d)],
        "enabled_dependents": enabled_dependents(manifest.id, state_dir),
    }

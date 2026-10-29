
from __future__ import annotations

import re
from typing import Any, Dict, List

import structlog

from src.cplugs.save.vault.manifest import ManifestError
from src.cplugs.save.vault.old_sources import labels
from src.cplugs.save.vault.store import Vault, unit_lock

logger = structlog.get_logger()

VERDICTS = ("keep", "junk")
DATE_RE = re.compile(r"^\d{8}$")


class ReviewRefused(ValueError):
    pass


def add_verdict(vault: Vault, unit: str, verdict: str, date: str) -> Dict[str, Any]:
    if verdict not in VERDICTS or not DATE_RE.match(date):
        raise ReviewRefused(f"a verdict is one of {VERDICTS} with a date like 20261022")
    with unit_lock(unit):
        ids = vault.manifests.point_ids(unit)
        if not ids:
            raise ReviewRefused(f"no unit {unit}")
        tags = vault.manifests.read_tags(unit, ids[-1])
        if not tags.get("imported"):
            raise ReviewRefused(f"{unit}: the newest point is not an import")
        found: List[str] = [x for x in tags.get("labels") or [] if not x.startswith(labels.REVIEWED_PREFIX)]
        found.append(f"{labels.REVIEWED_PREFIX}{date}:{verdict}")
        vault.manifests.write_tags(unit, ids[-1], {**tags, "labels": found})
    vault.changed()
    logger.info("save_import_reviewed", unit=unit, verdict=verdict)
    return {"unit": unit, "point_id": ids[-1], "labels": found}


def add_verdicts(vault: Vault, units: List[str], verdict: str, date: str) -> Dict[str, Any]:
    updated, refused = [], []
    for unit in units:
        try:
            updated.append(add_verdict(vault, unit, verdict, date))
        except (ReviewRefused, ManifestError) as exc:
            refused.append({"unit": unit, "reason": str(exc)[:200]})
    return {"updated": updated, "refused": refused}

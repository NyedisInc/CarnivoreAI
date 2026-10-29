
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.core.inventory.locations import Locations
from src.core.inventory.model import KEEP, REPORT, Artifact
from src.core.inventory.resolve import resolve_session
from src.core.session_purge import identity
from src.core.session_purge.model import PurgePlan, PurgeRefused

FINGERPRINT_CHARS = 16


def acting_material(artifacts: Iterable[Artifact]) -> List[Any]:
    return [a.material() for a in artifacts if a.action != REPORT]


def plan_material(plan: PurgePlan) -> Dict[str, Any]:
    return {"session": plan.session.as_dict(), "artifacts": acting_material(plan.artifacts),
            "blockers": sorted(plan.blockers), "shared": sorted(s["session_uuid"] for s in plan.shared_with)}


def fingerprint_of(plan: PurgePlan) -> str:
    blob = json.dumps(plan_material(plan), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:FINGERPRINT_CHARS]


def build_plan(conn: sqlite3.Connection, session_uuid: str, *, state_dir: Path, config_path: Path,
               panes: Tuple[bool, Iterable[Tuple[Any, Any, Any]]], live_row_ids: Iterable[str] = (),
               pins_path: Optional[Path] = None, homes: Optional[Iterable[Path]] = None,
               codex: Optional[Path] = None) -> PurgePlan:
    locations = Locations(state_dir=Path(state_dir), config_path=Path(config_path), pins_path=pins_path,
                          homes=tuple(homes) if homes is not None else None, codex=codex)
    found = resolve_session(conn, session_uuid, locations)
    ident = found.session
    plan = PurgePlan(session=ident, shared_with=found.shared_with)
    live = identity.live_blocker(ident, panes[0], panes[1], live_row_ids)
    if live:
        plan.blockers.append(live)
    plan.blockers += identity.static_blockers(conn, ident)
    plan.artifacts = found.artifacts
    plan.blockers += found.blockers
    if any(a.action == KEEP for a in plan.artifacts):
        plan.warnings.append("the purge is incomplete: the artifacts marked keep stay, and the reason says why")
    if not ident.conversation:
        plan.warnings.append("the row records no conversation id, so no transcript or Claude file could be traced")
    plan.fingerprint = fingerprint_of(plan)
    return plan


def require_quoted(plan: PurgePlan, quoted: Optional[str]) -> None:
    if not quoted or not quoted.strip():
        raise PurgeRefused(428, "apply needs plan_fingerprint: ask for the plan first (apply false), read it, "
                                "and send back its fingerprint")
    if quoted.strip() != plan.fingerprint:
        raise PurgeRefused(412, f"the plan changed since it was read (fingerprint {quoted.strip()} is now "
                                f"{plan.fingerprint}); read the new plan and quote it")

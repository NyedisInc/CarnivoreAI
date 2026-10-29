
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.cplugs.save.vault import adopt, constants as K
from src.cplugs.save.vault.manifest import HOME_CLAUDE, HOME_CODEX
from src.cplugs.save.vault.old_sources import runs
from src.cplugs.save.vault.old_sources.attribution import NO_PROJECT_GROUP
from src.cplugs.save.vault.old_sources.plan import PlannedPoint
from src.cplugs.save.vault.store import Vault
from src.core.deepsearch.fallback_hook import AdoptedPoint, FallbackPoint, IncomingFile

logger = structlog.get_logger()


def original_path(rel: str, claude_root: Path, codex_home: Path) -> str:
    return str(codex_home / rel) if rel.split("/", 1)[0] in ("sessions", "archived_sessions") else str(claude_root / rel.removeprefix("projects/"))


def to_incoming(point: PlannedPoint, run_id: str, claude_root: Path, codex_home: Path) -> FallbackPoint:
    home = HOME_CODEX if point.family == "codex" else HOME_CLAUDE
    files = tuple(IncomingFile(role=f.role, home=home, rel=f.rel, source_path=original_path(f.rel, claude_root, codex_home),
                               length=f.copy.length, sha256=f.copy.sha256,
                               mode=0o600, mtime_ns=int(f.copy.captured_epoch * 1e9), lines=0, read=f.copy.opener) for f in point.files)
    attribution = point.attribution
    return FallbackPoint(
        conversation_id=point.unit, point_id=point.point_id, reason=K.REASON_IMPORT, created_epoch=point.stamp,
        created_at=datetime.fromtimestamp(point.stamp, timezone.utc).isoformat(), family=point.family, files=files,
        project_uid=attribution.project_uid, project_name=attribution.project_name or NO_PROJECT_GROUP, working_dir=attribution.working_dir,
        encoded_folder=point.enc or None, tags={**point.tags, "run": run_id})


def expected_rows(points: List[FallbackPoint]) -> List[Dict[str, Any]]:
    return [{"unit": p.conversation_id, "source_point_id": p.point_id,
             "files": [{"home": f.home, "rel": f.rel, "length": f.length, "sha256": f.sha256} for f in p.files]} for p in points]


def file_points(vault: Vault, state: Path, run_id: str, points: List[FallbackPoint]) -> List[AdoptedPoint]:
    return adopt.adopt_points(vault, points, lambda entry: runs.append_undo(state, run_id, entry))


def receipt_of(run_id: str, results: List[AdoptedPoint], counts: Dict[str, Any], extras: Optional[str]) -> Dict[str, Any]:
    tally: Dict[str, int] = {}
    for r in results:
        tally[r.status] = tally.get(r.status, 0) + 1
    refused = [{"unit": r.conversation_id, "point": r.source_point_id, "reason": r.reason} for r in results if r.status == adopt.REFUSED]
    if not results:
        state = runs.STATE_NOOP
    else:
        state = runs.STATE_PARTIAL if refused else runs.STATE_DONE
    return {"run_id": run_id, "state": state, "finished_at": datetime.now(timezone.utc).isoformat(), "filed": tally, "refused": refused,
            "counts": counts, "extras_unit": extras, "points": [{"unit": r.conversation_id, "source_point_id": r.source_point_id, "point_id": r.point_id, "status": r.status}
                                                                 for r in results]}


def undo(vault: Vault, state: Path, run_id: str) -> Dict[str, Any]:
    receipt = runs.read_receipt(state, run_id)
    if receipt.get("state") == runs.STATE_UNDONE:
        raise runs.RunError(f"{run_id} was already undone")
    report = adopt.remove_adopted(vault, runs.read_undo(state, run_id))
    done = {**receipt, "state": runs.STATE_UNDONE, "undone_at": datetime.now(timezone.utc).isoformat(), "undo": report}
    runs.write_receipt(state, run_id, done)
    logger.info("save_import_undone", run_id=run_id, removed=len(report["removed"]), kept=len(report["kept"]), errors=len(report["errors"]))
    return {"run_id": run_id, "state": runs.STATE_UNDONE, "undo": report}

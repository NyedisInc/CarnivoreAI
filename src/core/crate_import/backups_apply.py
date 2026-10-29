
from __future__ import annotations

from typing import Any, Dict

import structlog

from src.core.crate_import import backups_in, files_apply
from src.core.crate_import.analysis import Analysis
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.hooks import ApplyHooks
from src.core.crate_import.model import ImportFailed
from src.core.crate_format.reader import CrateReader

logger = structlog.get_logger()


def apply(reader: CrateReader, a: Analysis, env: ImportEnv, hooks: ApplyHooks, placed: files_apply.PlacedFiles) -> Dict[str, Any]:
    view = a.backups
    if not view.get("carried"):
        return {}
    source = backups_in.adopter(env) if (a.prov.own or a.request.file_backups) else None
    if source is None or not view.get("restores"):
        return backups_in.receipt_block(view, [])
    excluded = sorted({r["id"] for r in view["conversations"] if r["status"] == backups_in.ST_NOT_RESTORED})
    points = backups_in.incoming_points(reader, a.backup_points, env, a.enc, a.decision.mapping,
                                        [u for u, _c in a.crate_sessions], excluded)
    try:
        results = source.adopt_points(points, lambda entry: files_apply.record_undo(hooks, placed, entry))
    except OSError as exc:
        raise ImportFailed(files_apply.E_IO, f"the backup vault: {type(exc).__name__}", rolled_back=False) from exc
    logger.info("crate_import_backups_filed", adopted=sum(1 for r in results if r.status == "adopted"),
                present=sum(1 for r in results if r.status == "present"), refused=sum(1 for r in results if r.status == "refused"))
    return backups_in.receipt_block(view, results)

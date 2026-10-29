
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

import structlog

from src.core.crate_format.reader import CrateReader
from src.core.crate_import import backups_folder_in as fin
from src.core.crate_import import backups_in
from src.core.crate_import.analysis import Analysis
from src.core.crate_import.env import ImportEnv

logger = structlog.get_logger()


def apply(reader: CrateReader, a: Analysis, env: ImportEnv, log: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    view = a.backups
    if not view.get("folders"):
        return {}
    source = backups_in.adopter(env)
    wanted = {r["unit"] for r in view["folders"] if r["status"] == backups_in.ST_RESTORE}
    if source is None or not wanted:
        return fin.receipt_block(view, [], {})
    placed: Dict[str, fin.Placed] = {}
    for unit in sorted(wanted):
        plugin, _dot, data = unit.partition(".")
        home = env.plugin_homes(plugin, data)
        if home is None or not Path(home.root).is_dir():
            continue
        placed[unit] = fin.repath(reader, unit, a.folder_points[unit], Path(home.root))
    points = [p for unit in sorted(placed) for p in placed[unit].points]
    results = source.adopt_points(points, log or (lambda entry: None)) if points else []
    logger.info("crate_import_folder_backups_filed", adopted=sum(1 for r in results if r.status == "adopted"),
                present=sum(1 for r in results if r.status == "present"), refused=sum(1 for r in results if r.status == "refused"),
                boards_not_placed=sum(len(p.missing) for p in placed.values()))
    return fin.receipt_block(view, results, placed)

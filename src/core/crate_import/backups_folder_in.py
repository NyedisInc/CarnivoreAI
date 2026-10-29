
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import structlog

from src.core.crate_format.model_files import FileRecord
from src.core.crate_format.reader import CrateReader
from src.core.crate_import import backups_in, plugin_data_in
from src.core.crate_import.backups_in import Point
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.model import W_STORE_NO_FOLDER, W_STORE_PLUGIN_OFF
from src.core.deepsearch import fallback_hook as fb

logger = structlog.get_logger()

SCOPE_BOARDS = "task_item_id"
HOME, ROLE = "folder", "folder_file"
_UNIT = re.compile(r"^[a-z][a-z0-9_-]{0,63}\.[a-z][a-z0-9_-]{0,63}$")
R_NO_BOARDS = "board_not_placed"


def unit_ok(unit: str) -> bool:
    return bool(_UNIT.match(unit))


def carried(reader: CrateReader, files: Sequence[FileRecord]) -> Dict[str, List[Point]]:
    return {u: pts for u, pts in backups_in.carried(reader, files, folders=True).items() if unit_ok(u)}


def _board_dirs(point: Point) -> List[str]:
    return sorted({posixpath.dirname(str(i["rel"])) for i in point.meta["files"]
                   if posixpath.basename(str(i["rel"])) == plugin_data_in.BOARD_SIDECAR and posixpath.dirname(str(i["rel"]))})


def _slugs(points: Sequence[Point]) -> List[str]:
    return sorted({posixpath.basename(d) for p in points for d in _board_dirs(p)})


@dataclass
class FolderCtx:

    env: ImportEnv
    chosen: Callable[[str], bool]
    restoring: bool
    stores: Dict[str, plugin_data_in.Store] = field(default_factory=dict)


def _home(unit: str, ctx: FolderCtx) -> Any:
    plugin, _dot, data = unit.partition(".")
    if not ctx.env.plugin_enabled(plugin):
        return None, W_STORE_PLUGIN_OFF
    home = ctx.env.plugin_homes(plugin, data)
    if home is None or Path(home.root).is_symlink():
        return None, W_STORE_NO_FOLDER
    if not Path(home.root).is_dir() and not (home.default and ctx.restoring):
        return None, W_STORE_NO_FOLDER
    return home, None


def _placeable(points: Sequence[Point], root: Path, store: Optional[plugin_data_in.Store], restoring: bool) -> bool:
    coming = {u.slug for u in store.units} if store is not None and restoring else set()
    return any(slug in coming or plugin_data_in.find_board(root, slug) is not None for slug in _slugs(points))


def plan_rows(found: Dict[str, List[Point]], ctx: FolderCtx, source: Optional[Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for unit, points in sorted(found.items()):
        reason: Optional[str] = None
        home = None
        if not ctx.chosen(unit):
            reason = backups_in.R_NOT_CHOSEN
        elif source is None:
            reason = backups_in.R_PLUGIN_OFF
        else:
            home, reason = _home(unit, ctx)
            if home is not None and points[0].meta.get("scope_by") == SCOPE_BOARDS and not _placeable(points, Path(home.root), ctx.stores.get(unit), ctx.restoring):
                reason = R_NO_BOARDS
        already = _already(source, unit, points) if reason is None else 0
        status = backups_in.ST_NOT_RESTORED if reason else (backups_in.ST_PRESENT if already == len(points) else backups_in.ST_RESTORE)
        rows.append({"id": unit, "unit": unit, "plugin": unit.partition(".")[0], "kind": backups_in.KIND_FOLDER, "points": len(points),
                     "files": sum(len(p.records) for p in points), "bytes": sum(p.bytes for p in points), "already": already,
                     "status": status, "reason": reason})
    return rows


def _already(source: Any, unit: str, points: Sequence[Point]) -> int:
    try:
        held = {p.point_id for p in source.list_folder_points(unit)}
    except (OSError, fb.FallbackUnavailable, AttributeError):
        return 0
    return sum(1 for p in points if p.point_id in held)


def merge_view(view: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    view["folders"] = rows
    view["carried"] = bool(view.get("carried")) or bool(rows)
    view["restores_folders"] = any(r["status"] == backups_in.ST_RESTORE for r in rows)
    return view


def not_restored(view: Dict[str, Any]) -> List[Dict[str, str]]:
    return [{"what": f"backups:{r['id']}", "why": r["reason"]} for r in view.get("folders", []) if r["status"] == backups_in.ST_NOT_RESTORED]


@dataclass
class Placed:

    points: List[fb.FallbackPoint] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    left_out: int = 0


def _file(reader: CrateReader, point: Point, item: Dict[str, Any], rel: str, root: Path) -> fb.IncomingFile:
    record = point.records[item["n"]]
    return fb.IncomingFile(role=ROLE, home=HOME, rel=rel, source_path=str(root / rel), length=int(item["length"]), sha256=record.content_sha256,
                           mode=int(item.get("mode") or 0), mtime_ns=int(item.get("mtime_ns") or 0), lines=0,
                           read=lambda r=record: reader.file_chunks(r))


def repath(reader: CrateReader, unit: str, points: Sequence[Point], root: Path) -> Placed:
    out = Placed()
    where: Dict[str, Optional[str]] = {}

    def place(slug: str) -> Optional[str]:
        if slug not in where:
            found = plugin_data_in.find_board(root, slug)
            where[slug] = found.relative_to(root).as_posix() if found is not None else None
        return where[slug]

    for point in points:
        by_board = point.meta.get("scope_by") == SCOPE_BOARDS
        dirs = _board_dirs(point) if by_board else []
        files: List[fb.FallbackPointFile] = []
        for item in point.meta["files"]:
            rel = str(item["rel"])
            if by_board:
                board = next((d for d in dirs if rel.startswith(d + "/")), None)
                target = place(posixpath.basename(board)) if board is not None else None
                if board is None or target is None:
                    out.left_out += 1
                    if board is not None and posixpath.basename(board) not in out.missing:
                        out.missing.append(posixpath.basename(board))
                    continue
                rel = f"{target}{rel[len(board):]}"
            files.append(_file(reader, point, item, rel, root))
        if files:
            meta = point.meta
            out.points.append(fb.FallbackPoint(
                conversation_id=unit, point_id=point.point_id, reason=str(meta.get("reason") or "import"),
                created_epoch=float(meta.get("created_epoch") or 0), created_at=str(meta.get("created_at") or ""), family="plugin",
                files=tuple(files), working_dir=str(root), kind=backups_in.KIND_FOLDER))
    out.missing.sort()
    return out


def receipt_block(view: Dict[str, Any], results: Sequence[fb.AdoptedPoint], placed: Dict[str, Placed]) -> Dict[str, Any]:
    return {"adopted": sum(1 for r in results if r.status == "adopted"), "present": backups_in.present_total(view.get("folders", []), results),
            "refused": [{"unit": r.conversation_id, "point": r.source_point_id, "reason": r.reason} for r in results if r.status == "refused"],
            "board_not_placed": {u: p.missing for u, p in sorted(placed.items()) if p.missing},
            "not_restored": not_restored(view)}

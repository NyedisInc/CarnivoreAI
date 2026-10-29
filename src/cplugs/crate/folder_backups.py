
from __future__ import annotations

import dataclasses
import posixpath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from src.cplugs.crate import constants as K
from src.cplugs.crate import policy as P
from src.cplugs.crate.backup_points import plan_point
from src.cplugs.crate.vault_files import VaultWalk
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs
from src.core.deepsearch import fallback_hook as fb

SCOPE_BOARDS, BOARD_SIDECAR = "task_item_id", "sidecar.json"
_OK = "ok"
_REFUSED = {"plugin_off": "the {plugin} plugin is off, so its folder is not backed up now",
            "switched_off": "the {plugin} folder is switched off in the backup menu"}


def _board_dirs(point: fb.FallbackPoint) -> Set[str]:
    return {posixpath.dirname(f.rel) for f in point.files if posixpath.basename(f.rel) == BOARD_SIDECAR and posixpath.dirname(f.rel)}


def cut_to_scope(point: fb.FallbackPoint, family: Mapping[str, Any]) -> Optional[fb.FallbackPoint]:
    units = [u for u in family.get("units") or [] if isinstance(u, Mapping) and u.get("rel")]
    if family.get("scope_by") == SCOPE_BOARDS:
        slugs = {posixpath.basename(str(u["rel"])) for u in units if u.get("dir")}
        boards = [d for d in _board_dirs(point) if posixpath.basename(d) in slugs]
        kept = [f for f in point.files if any(f.rel.startswith(d + "/") for d in boards)]
    else:
        rels = [str(u["rel"]) for u in units]
        kept = [f for f in point.files if any(f.rel == r or f.rel.startswith(r.rstrip("/") + "/") for r in rels)]
    return dataclasses.replace(point, files=tuple(kept)) if kept else None


@dataclasses.dataclass
class FolderBackups:

    walk: VaultWalk = dataclasses.field(default_factory=VaultWalk)
    carried: List[Dict[str, Any]] = dataclasses.field(default_factory=list)


def _points_of(source: Any, unit: str, family: Mapping[str, Any]) -> List[fb.FallbackPoint]:
    cut = (cut_to_scope(p, family) for p in source.list_folder_points(unit))
    return [p for p in cut if p is not None]


def plan_folder_backups(requested: Sequence[str], families: Sequence[Mapping[str, Any]], provider: Optional[str],
                        sources: Optional[Sequence[Any]] = None) -> FolderBackups:
    out = FolderBackups()
    by_unit = {str(f["unit"]): f for f in families}
    chosen = [s for s in (cs.fallback_sources() if sources is None else sources) if hasattr(s, "list_folder_points")]
    for unit in sorted(set(requested)):
        family = by_unit.get(unit)
        if family is None:
            out.walk.blockers.append((K.B_BACKUP_FOLDER_UNKNOWN, f"{unit} is not a plugin folder this project has backups of"))
            continue
        if family["state"] != _OK:
            out.walk.blockers.append((K.B_BACKUP_FOLDER_OFF, f"backups of {unit} were ticked but " + _REFUSED[str(family["state"])].format(plugin=family["plugin"])))
            continue
        if provider is None or not chosen:
            out.walk.blockers.append((K.B_BACKUPS_OFF, f"backups of {unit} were ticked and the backup plugin is off"))
            continue
        _carry(out, unit, family, provider, chosen)
    return out


def _carry(out: FolderBackups, unit: str, family: Mapping[str, Any], provider: str, chosen: Sequence[Any]) -> None:
    for source in chosen:
        try:
            points = _points_of(source, unit, family)
        except OSError as exc:
            out.walk.blockers.append((K.B_VAULT, f"the backup of {unit} cannot be reached ({type(exc).__name__})"))
            return
        except fb.FallbackUnavailable as exc:
            out.walk.blockers.append((K.B_VAULT_INCOMPLETE, f"the backup points of {unit} cannot be read ({exc})"))
            return
        if not points:
            continue
        files: List[Any] = []
        for point in points:
            try:
                files += plan_point(provider, unit, point, str(family.get("scope_by") or ""))
            except cf.UnsafeName as exc:
                out.walk.warnings.append(f"backup_point_skipped: {point.point_id} of {unit} has a name a crate cannot carry ({exc})")
        if not files:
            return
        out.walk.files += files
        size = sum(f.size for f in files)
        out.walk.reconcile.append({"store": cs.STORE_VAULT, "kind": cs.KIND_FILE, "inventory_count": len(files), "inventory_size": size,
                                   "decision": P.CARRY, "what": f"backups:{unit}",
                                   "reason": f"every backup point of {unit}, cut to this project's part (backup_units)"})
        out.carried.append({"family": unit, "unit": unit, "plugin": family["plugin"], "points": len(points),
                            "files": sum(len(p.files) for p in points), "bytes": sum(f.length for p in points for f in p.files)})
        return

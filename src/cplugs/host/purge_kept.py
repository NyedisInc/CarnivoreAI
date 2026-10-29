
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

import structlog

from src.cplugs.host import data_roots
from src.cplugs.sdk.data_decl import DataDecl

logger = structlog.get_logger()


def _inside(rel: str, root: str) -> bool:
    return rel == root or rel.startswith(root.rstrip("/") + "/")


def kept_state_paths(decls: Iterable[DataDecl]) -> Tuple[str, ...]:
    out: List[str] = []
    for d in decls:
        if d.outlives_purge:
            rel = d.state_path or d.default
            if rel:
                out.append(rel)
    return tuple(out)


def deletable_owned_files(owned: Iterable[str], decls: Iterable[DataDecl]) -> Tuple[str, ...]:
    kept = kept_state_paths(decls)
    out: List[str] = []
    for rel in owned:
        if any(_inside(rel, k) or _inside(k, rel) for k in kept):
            logger.warning("cplug_purge_owned_path_kept", path=rel, reason="a declared store with purge kept sits there")
            continue
        out.append(rel)
    return tuple(out)


def kept_stores(state_dir: Path, decls: Iterable[DataDecl], settings: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for d in decls:
        if not d.outlives_purge:
            continue
        root = data_roots.decl_root(state_dir, "", d, settings)
        location = str(root) if root is not None else ""
        rows.append({"id": d.id, "location": location, "exists": bool(location) and Path(location).exists(), "reason": d.policy.reason})
    return rows

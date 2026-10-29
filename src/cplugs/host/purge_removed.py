
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List, Mapping

import structlog

from src.cplugs.host import data_roots
from src.cplugs.host.purge_owned import PurgePathRefused
from src.cplugs.sdk.data_decl import DataDecl

logger = structlog.get_logger()

PURGE_REMOVED = "removed"


def _overlaps(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def _resolved(path: Path) -> Path:
    return path.parent.resolve() / path.name


def _check_root(state_dir: Path, decl: DataDecl, root: Path) -> Path:
    state = state_dir.resolve()
    resolved = _resolved(root)
    if resolved.is_symlink():
        raise PurgePathRefused(f"store {decl.id}: {root} is a symlink, a purge never follows one")
    if decl.state_path or not decl.root_setting or resolved.is_relative_to(state):
        if state not in resolved.parents:
            raise PurgePathRefused(f"store {decl.id}: {root} resolves outside {state_dir}")
        return resolved
    if resolved.parent == resolved or resolved == Path.home().resolve() or _overlaps(resolved, state):
        raise PurgePathRefused(f"store {decl.id}: {root} is too broad to delete (the filesystem root, the home folder or the state folder)")
    return resolved


def resolve_roots(state_dir: Path, plugin_id: str, decls: Iterable[DataDecl], settings: Mapping[str, Any]) -> List[Path]:
    decls = list(decls)
    kept = [r for d in decls if d.outlives_purge and (r := data_roots.decl_root(state_dir, plugin_id, d, settings)) is not None]
    kept_resolved = [_resolved(k) for k in kept]
    out: List[Path] = []
    for decl in decls:
        if decl.policy.purge != PURGE_REMOVED or decl.path:
            continue
        root = data_roots.decl_root(state_dir, plugin_id, decl, settings)
        if root is None:
            continue
        resolved = _check_root(state_dir, decl, root)
        if any(_overlaps(resolved, k) for k in kept_resolved):
            logger.warning("cplug_purge_removed_store_kept", cplug=plugin_id, store=decl.id, reason="it overlaps a store with purge kept")
            continue
        out.append(resolved)
    return out

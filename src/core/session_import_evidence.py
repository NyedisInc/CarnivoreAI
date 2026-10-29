
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Sequence, Set, Tuple

import structlog

from src.core.session_import_ladder import LadderEvidence, LiveSession

logger = structlog.get_logger()

PIPE_PREFIX = "tmux_"
PIPE_EXT_PREFIX = "tmux_ext_"
PIPE_SUFFIX = ".pipe"


def scan_pipe_files(
    log_dir: Optional[Path],
) -> Tuple[Optional[frozenset], Optional[frozenset]]:
    if log_dir is None:
        return (None, None)
    try:
        names = [p.name for p in Path(log_dir).iterdir() if p.is_file()]
    except (OSError, ValueError) as exc:
        logger.warning(
            "pipe_scan_unreadable",
            log_dir=str(log_dir),
            error=str(exc),
            note=(
                "tier 3 of the evidence ladder is UNEVALUATED for every "
                "session on this run, not a miss"
            ),
        )
        return (None, None)

    created: Set[str] = set()
    ext: Set[str] = set()
    for name in names:
        if not name.startswith(PIPE_PREFIX) or not name.endswith(PIPE_SUFFIX):
            continue
        if name.startswith(PIPE_EXT_PREFIX):
            ext.add(name[len(PIPE_EXT_PREFIX):-len(PIPE_SUFFIX)])
        else:
            created.add(name[len(PIPE_PREFIX):-len(PIPE_SUFFIX)])
    return (frozenset(created), frozenset(ext))


def ext_pipe_live_names(
    live_names: Iterable[str], ext_slugs: Optional[frozenset]
) -> frozenset:
    if not ext_slugs:
        return frozenset()
    from src.core.tmux_backend import _slugify

    return frozenset(n for n in live_names if _slugify(n) in ext_slugs)


def probe_origin_markers(
    live_names: Sequence[str],
    probe: Optional[Callable[[str], Optional[str]]],
) -> Tuple[Dict[str, str], frozenset]:
    if probe is None:
        return ({}, frozenset())
    markers: Dict[str, str] = {}
    failures: Set[str] = set()
    for name in live_names:
        try:
            value = probe(name)
        except (OSError, ValueError, RuntimeError) as exc:
            logger.warning(
                "origin_marker_probe_failed", tmux_name=name, error=str(exc)
            )
            failures.add(name)
            continue
        if value is not None:
            markers[name] = str(value)
    return (markers, frozenset(failures))


def gather(
    conn: sqlite3.Connection,
    *,
    live_names: Sequence[str],
    owned_tmux_names: Optional[Iterable[str]],
    log_dir: Optional[Path],
    project_roots: Sequence[str] = (),
    origin_probe: Optional[Callable[[str], Optional[str]]] = None,
) -> LadderEvidence:
    from src.core.session_stage_a_boundary import read_boundary

    created_slugs, ext_slugs = scan_pipe_files(log_dir)
    markers, failures = probe_origin_markers(list(live_names), origin_probe)
    return LadderEvidence(
        owned_tmux_names=(
            None if owned_tmux_names is None else frozenset(owned_tmux_names)
        ),
        created_pipe_slugs=created_slugs,
        ext_pipe_names=ext_pipe_live_names(live_names, ext_slugs),
        origin_markers=markers,
        origin_probe_failures=failures,
        stage_a_boundary_epoch=read_boundary(conn),
        project_roots=tuple(project_roots),
    )


def live_sessions_from(rows: Iterable[dict]) -> Tuple[LiveSession, ...]:
    out = []
    for row in rows:
        name = row.get("name")
        if not name:
            continue
        out.append(
            LiveSession(
                tmux_name=str(name),
                epoch=row.get("tmux_created_epoch"),
                working_dir=row.get("working_dir"),
            )
        )
    return tuple(out)

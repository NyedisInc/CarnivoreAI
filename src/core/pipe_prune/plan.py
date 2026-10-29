
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

from src.core.product_identity import strip_session_prefix

PIPE_PREFIX: str = "tmux_"
PIPE_SUFFIX: str = ".pipe"

REMOTE_MIRROR_PREFIX: str = "tmux_rh_"

LEGACY_PREFIXES: tuple[str, ...] = ("ext_",)


class Verdict(str, Enum):

    PRUNE = "prune"
    KEEP_PRESENT = "keep_present_session"
    KEEP_OWNED = "keep_named_by_live_pane"
    KEEP_OPEN = "keep_open_by_a_process"
    KEEP_YOUNG = "keep_younger_than_safe_age"
    KEEP_UNREADABLE = "keep_stat_failed"


class Refusal(str, Enum):

    TMUX_UNKNOWN = "tmux_answer_unknown_or_incomplete"
    NO_PANES = "zero_panes_read"
    LADDER_PENDING = "import_ladder_not_yet_consumed"
    OPEN_CHECK_FAILED = "open_file_check_unavailable"


@dataclass(frozen=True)
class PaneFacts:

    complete: bool
    session_names: frozenset = frozenset()
    owner_paths: frozenset = frozenset()


@dataclass(frozen=True)
class Decision:

    path: Path
    verdict: Verdict
    size: int = 0
    age_hours: float = 0.0


def refusal_for(
    facts: PaneFacts, ladder_consumed: bool, open_paths: Optional[frozenset]
) -> Optional[Refusal]:
    if not facts.complete:
        return Refusal.TMUX_UNKNOWN
    if not facts.session_names:
        return Refusal.NO_PANES
    if not ladder_consumed:
        return Refusal.LADDER_PENDING
    if open_paths is None:
        return Refusal.OPEN_CHECK_FAILED
    return None


def _slugify(raw: str) -> str:
    from src.core.tmux_backend import _slugify as slugify

    return slugify(raw)


def present_stems(session_names: Iterable[str]) -> frozenset:
    stems: set[str] = set()
    for name in session_names:
        stems.add(_slugify(name))
        stems.add(_slugify("adopted:" + name))
        slug = strip_session_prefix(name)
        if slug:
            stems.add(slug)
    return frozenset(stems)


def file_stem_candidates(filename: str) -> frozenset:
    stem = filename[len(PIPE_PREFIX):-len(PIPE_SUFFIX)]
    out = {stem}
    for prefix in LEGACY_PREFIXES:
        if stem.startswith(prefix):
            out.add(stem[len(prefix):])
    return frozenset(out)


def is_prunable_shape(path: Path) -> bool:
    name = path.name
    if not (name.startswith(PIPE_PREFIX) and name.endswith(PIPE_SUFFIX)):
        return False
    if name.startswith(REMOTE_MIRROR_PREFIX):
        return False
    return path.is_file() and not path.is_symlink()


def plan_prune(
    files: Iterable[Path],
    facts: PaneFacts,
    open_paths: frozenset,
    now: float,
    min_age_seconds: float,
) -> list[Decision]:
    stems = present_stems(facts.session_names)
    owned = frozenset(os.path.realpath(p) for p in facts.owner_paths)
    decisions: list[Decision] = []
    for path in files:
        try:
            st = path.stat()
        except OSError:
            decisions.append(Decision(path, Verdict.KEEP_UNREADABLE))
            continue
        age_hours = max(0.0, (now - st.st_mtime) / 3600.0)
        real = os.path.realpath(path)

        def decide(verdict: Verdict) -> Decision:
            return Decision(path, verdict, st.st_size, age_hours)

        if file_stem_candidates(path.name) & stems:
            decisions.append(decide(Verdict.KEEP_PRESENT))
        elif real in owned:
            decisions.append(decide(Verdict.KEEP_OWNED))
        elif real in open_paths:
            decisions.append(decide(Verdict.KEEP_OPEN))
        elif now - st.st_mtime < min_age_seconds:
            decisions.append(decide(Verdict.KEEP_YOUNG))
        else:
            decisions.append(decide(Verdict.PRUNE))
    return decisions

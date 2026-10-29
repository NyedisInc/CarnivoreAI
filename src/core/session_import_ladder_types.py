
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.core.product_identity import LEGACY_TMUX_SESSION_PREFIXES, TMUX_SESSION_PREFIX


LADDER_OURS = "ours"
LADDER_THEIRS = "theirs"
LADDER_UNKNOWN = "unknown"

REASON_NO_EVIDENCE = "no_admissible_evidence"
REASON_COULD_NOT_EVALUATE = "could_not_evaluate"

TIER_HIT = "hit"
TIER_MISS = "miss"
TIER_UNEVALUATED = "unevaluated"

INADMISSIBLE_TIERS: Tuple[int, ...] = (2,)

SESSION_PREFIX = TMUX_SESSION_PREFIX

ALL_MINT_PREFIXES: Tuple[str, ...] = (TMUX_SESSION_PREFIX, *LEGACY_TMUX_SESSION_PREFIXES)

AUTO_NAME_RE = re.compile(
    "^(?:" + "|".join(re.escape(p) for p in ALL_MINT_PREFIXES) + r")ses_[0-9a-f]{8}$"
)

ORIGIN_MARKER_CREATED = "created"


@dataclass(frozen=True)
class LiveSession:

    tmux_name: str
    epoch: Optional[int] = None
    working_dir: Optional[str] = None


@dataclass(frozen=True)
class TierOutcome:

    tier: int
    name: str
    result: str
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        if self.tier in INADMISSIBLE_TIERS:
            raise ValueError(
                f"tier {self.tier} is INADMISSIBLE and may never appear in a "
                "verdict: it records the app's own verdict, produced by the "
                "bug this import exists to correct. See the module docstring."
            )


@dataclass(frozen=True)
class LadderEvidence:

    owned_tmux_names: Optional[frozenset] = None
    created_pipe_slugs: Optional[frozenset] = None
    ext_pipe_names: frozenset = frozenset()
    origin_markers: Mapping[str, str] = field(default_factory=dict)
    origin_probe_failures: frozenset = frozenset()
    stage_a_boundary_epoch: Optional[int] = None
    project_roots: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionVerdict:

    tmux_name: str
    epoch: Optional[int]
    verdict: str
    reason: str
    tiers: Tuple[TierOutcome, ...] = ()
    hints: Tuple[str, ...] = ()
    unevaluated: Tuple[str, ...] = ()
    readopted: bool = False

    @property
    def could_not_evaluate(self) -> bool:
        return self.reason == REASON_COULD_NOT_EVALUATE

    def as_unattributed_record(self) -> Dict[str, Any]:
        return {
            "tmux_name": self.tmux_name,
            "epoch": self.epoch,
            "hints": list(self.hints),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LadderReport:

    verdicts: Tuple[SessionVerdict, ...] = ()

    @property
    def ours(self) -> List[SessionVerdict]:
        return [v for v in self.verdicts if v.verdict == LADDER_OURS]

    @property
    def theirs(self) -> List[SessionVerdict]:
        return [v for v in self.verdicts if v.verdict == LADDER_THEIRS]

    @property
    def unknown(self) -> List[SessionVerdict]:
        return [v for v in self.verdicts if v.verdict == LADDER_UNKNOWN]

    @property
    def unknown_no_evidence(self) -> List[SessionVerdict]:
        return [v for v in self.unknown if v.reason == REASON_NO_EVIDENCE]

    @property
    def unknown_unevaluated(self) -> List[SessionVerdict]:
        return [v for v in self.unknown if v.could_not_evaluate]

    def unattributed_records(self) -> List[Dict[str, Any]]:
        return [v.as_unattributed_record() for v in self.unknown]

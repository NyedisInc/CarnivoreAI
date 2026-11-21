
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

from src.core.attention.transcript_contract import check_transcript_line

MAX_SIGNATURES: int = 64


@dataclass
class ShapeLedger:

    last_seen: Dict[Tuple[str, ...], int] = field(default_factory=dict)

    def check(self, record: Any, offset: int) -> None:
        verdict = check_transcript_line(record)
        if verdict is None or verdict.recognized:
            return
        self.last_seen[tuple(verdict.problems)] = offset
        if len(self.last_seen) > MAX_SIGNATURES:
            oldest = min(self.last_seen, key=self.last_seen.__getitem__)
            del self.last_seen[oldest]

    def problems_within(self, window_start: int) -> Tuple[str, ...]:
        found = {p for sig, at in self.last_seen.items() if at >= window_start for p in sig}
        return tuple(sorted(found))

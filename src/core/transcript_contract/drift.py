
from __future__ import annotations

from collections import Counter
from typing import Any, Dict

from src.core.transcript_contract.parsed import STATUS_OK, ParsedLine


class DriftTally:

    def __init__(self) -> None:
        self.lines: Counter = Counter()
        self.kinds: Counter = Counter()
        self.findings: Counter = Counter()

    def observe(self, parsed: ParsedLine) -> None:
        self.lines[f"{parsed.family}:{parsed.status}"] += 1
        if parsed.status != STATUS_OK:
            return
        self.kinds[f"{parsed.family}:{parsed.kind}:{'known' if parsed.known else 'unknown'}"] += 1
        for finding in set(f.key() for f in parsed.findings):
            self.findings[f"{parsed.family}:{parsed.kind}:{finding}"] += 1

    def observe_status(self, family: str, status: str) -> None:
        self.lines[f"{family}:{status}"] += 1

    def merge(self, other: "DriftTally") -> None:
        self.lines.update(other.lines)
        self.kinds.update(other.kinds)
        self.findings.update(other.findings)

    @property
    def new_shapes(self) -> Dict[str, int]:
        return dict(self.findings.most_common())

    def to_json(self) -> Dict[str, Any]:
        return {
            "lines": dict(sorted(self.lines.items())),
            "kinds": dict(sorted(self.kinds.items())),
            "new_shapes": self.new_shapes,
        }

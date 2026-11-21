
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, NamedTuple, Optional, Tuple

from src.core.mcp_health.fold import McpEvent
from src.core.mcp_health.history import MAX_EVENTS, SCAN_MAX_BYTES, HistoryEntry, join_history
from src.core.timeline.stamps import WINDOW_RETENTION_BYTES

MAX_HEALS_PER_SERVER: int = 64
TRIM_ABOVE: int = 2 * MAX_EVENTS
MAX_OPEN_CALLS: int = 256


class McpRec(NamedTuple):

    offset: int
    call: Optional[int]
    event: McpEvent


@dataclass
class McpLog:

    recs: List[McpRec] = field(default_factory=list)
    history: HistoryEntry = field(default_factory=HistoryEntry)

    def add(self, offset: int, call: Optional[int], event: McpEvent) -> None:
        self.recs.append(McpRec(offset, call, event))

    def trim(self, cursor: int, retain_bytes: int = WINDOW_RETENTION_BYTES) -> None:
        if len(self.recs) <= TRIM_ABOVE:
            return
        state_floor = cursor - SCAN_MAX_BYTES - retain_bytes
        heal_floor = cursor - retain_bytes
        states = [r for r in self.recs if r.call is None and r.offset >= state_floor][-MAX_EVENTS:]
        per_server: Dict[str, List[McpRec]] = {}
        for rec in self.recs:
            if rec.call is not None and rec.offset >= heal_floor and rec.event.added:
                per_server.setdefault(rec.event.added[0], []).append(rec)
        heals = [r for group in per_server.values() for r in group[-MAX_HEALS_PER_SERVER:]]
        self.recs = sorted(states + heals, key=lambda r: r.offset)

    def forget_history(self) -> None:
        self.history = HistoryEntry()

    def joined(self, bound: int, file_size: int) -> Tuple[McpEvent, ...]:
        if self.history.is_stale(file_size):
            self.forget_history()
        return self._pass(self.history, bound, file_size)

    def merged(self, bound: int) -> Tuple[McpEvent, ...]:
        return self._pass(HistoryEntry(), bound, bound)

    def _pass(self, entry: HistoryEntry, bound: int, file_size: int) -> Tuple[McpEvent, ...]:
        scan_from = entry.scan_start(bound)
        found = [
            r.event for r in self.recs
            if r.call is None and scan_from < bound and r.offset < bound and (r.offset >= scan_from if scan_from == 0 else r.offset > scan_from)
        ]
        window = [r.event for r in self.recs if r.offset >= bound and (r.call is None or r.call >= bound)]
        merged = join_history(entry.events, found, window)
        entry.record(merged, file_size)
        return tuple(merged)

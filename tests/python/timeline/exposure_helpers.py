
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.pipeline import contract as C, plugin_db
from src.core.timeline import cursor as cursors, hot, plugin, reading
from src.core.transcript_contract.lines import parse_range
from tests.python.timeline.fold_fixtures import assistant, call, result, turn_end, user

CONV = "e5000001-0000-4000-9000-000000000000"
SESSION = "5e550000-0000-4000-9000-000000000001"
FAMILY = "claude"


@dataclass
class Switch:

    on: bool = True


class Clock:

    def __init__(self) -> None:
        self.t = 100.0
        self.timers: List[Tuple[float, Callable[..., None], tuple]] = []

    def now(self) -> float:
        return self.t

    def later(self, delay: float, fn: Callable[..., None], *args: Any) -> Any:
        entry = (self.t + delay, fn, args)
        self.timers.append(entry)

        class Handle:

            def cancel(_self) -> None:  # noqa: N805
                if entry in self.timers:
                    self.timers.remove(entry)

        return Handle()

    def advance(self, seconds: float) -> None:
        end = self.t + seconds
        while True:
            due = sorted(t for t in self.timers if t[0] <= end)
            if not due:
                break
            entry = due[0]
            self.timers.remove(entry)
            self.t = max(self.t, entry[0])
            entry[1](*entry[2])
        self.t = end


def append(path: Path, records: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")).encode() + b"\n")


def turn(second: int, tag: str) -> List[Dict[str, Any]]:
    return [user(second, f"prompt {tag}"), assistant(second + 1, [{"type": "text", "text": f"reply {tag}"}], msg=f"m{tag}", stop="end_turn"),
            turn_end(second + 2)]


def step(path: Path) -> None:
    hot.DRIVER.facts_at(str(path), path.stat().st_size)


def build_index(state: Path, main: Path, upto: int | None = None) -> None:
    data = main.read_bytes()[:upto]
    path = plugin_db.db_path(state, plugin.TIMELINE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, isolation_level=None)) as conn:
        plugin.TIMELINE.migrate(conn, 0)
        rng = parse_range(data, 0, "claude")
        plugin.TIMELINE.on_events(conn, (C.Appended(
            conversation_id=CONV, family="claude", path=str(main.resolve()), file_kind="conversation", start=0, end=rng.complete_end,
            lines=rng.lines, inherited_start=0, inherited_end=0, lineage=None, trigger="test"),))


@dataclass
class Client:

    path_of: Callable[[str], str]
    pos: Dict[str, Optional[cursors.Cursor]] = field(default_factory=dict)
    seen: List[str] = field(default_factory=list)
    kinds: List[str] = field(default_factory=list)
    turns: List[Optional[int]] = field(default_factory=list)

    def on_frame(self, frame: Dict[str, Any]) -> None:
        for file_key, (offset, _serial) in frame["moved"].items():
            held = self.pos.get(file_key)
            if held is None or offset > held.offset:
                self.catch_up(file_key)

    def catch_up(self, file_key: str) -> None:
        while True:
            page = reading.read_forward(self.path_of(file_key), CONV, file_key, self.pos.get(file_key))
            assert page.reset is None
            for event in page.events:
                self.seen.append(event.id)
                self.kinds.append(event.kind.value)
                self.turns.append(event.turn)
            if page.end > 0:
                self.pos[file_key] = cursors.Cursor(CONV, file_key, page.end, page.last_serial or "")
            if page.at_end or not page.events:
                return


__all__ = ["CONV", "SESSION", "FAMILY", "Client", "Clock", "Switch", "append", "build_index", "step", "turn", "assistant", "call", "result", "user"]

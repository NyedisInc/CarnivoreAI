
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from src.core.db_models import TRAIL_CLOSING_STATUSES, TRAIL_STATUS_STARTED
from src.core.trail_entry import REQUIRED_FIELDS, TrailEntry, utc_now

_UUID_RE = re.compile(r'"entry_uuid"\s*:\s*"([^"]+)"')
_KIND_RE = re.compile(r'"kind"\s*:\s*"([^"]+)"')
_STARTED_AT_RE = re.compile(r'"started_at"\s*:\s*"([^"]+)"')

TRAIL_READ_OK = "ok"
TRAIL_READ_ABSENT = "absent"
TRAIL_READ_TRUNCATED_TAIL = "truncated_tail"
TRAIL_READ_UNREADABLE = "unreadable"


@dataclass
class TrailReadResult:

    status: str
    entries: List[TrailEntry] = field(default_factory=list)
    corrupt_line_no: Optional[int] = None
    error: Optional[str] = None
    line_count: int = 0

    @property
    def is_usable(self) -> bool:
        return self.status != TRAIL_READ_UNREADABLE


def _recover_partial_line(raw: str) -> Optional[TrailEntry]:
    """Rebuild what can be salvaged from a line cut off mid-write.

    Description: implements design section 9.4 case 3. A process killed
      during write() leaves a prefix of a line. Because entry_uuid and
      kind are written FIRST (see FIELD_ORDER), that prefix usually still
      carries both, which is enough to treat the record as an unclosed
      ``started`` entry - identical handling to case 2. When the prefix is
      too short to carry them, no entry is recovered and the caller
      escalates that ONE line to the unreadable state.
    Inputs: raw (str) - the incomplete final line, without a newline.
    Output: TrailEntry | None - a synthetic entry with
      ``recovered_partial=True`` and ``status='started'``, or None when
      entry_uuid or kind could not be read out of the fragment.
    """
    uuid_match = _UUID_RE.search(raw)
    kind_match = _KIND_RE.search(raw)
    if not uuid_match or not kind_match:
        return None
    started_match = _STARTED_AT_RE.search(raw)
    return TrailEntry(
        entry_uuid=uuid_match.group(1),
        kind=kind_match.group(1),
        status=TRAIL_STATUS_STARTED,
        started_at=started_match.group(1) if started_match else utc_now(),
        detail="recovered from a truncated trail line",
        recovered_partial=True,
    )


def read_trail(path: Path) -> TrailReadResult:
    """Parse migration_trail.jsonl into a three-outcome read result.

    Description: implements design section 9.4 cases 1 to 4.

      * File absent  -> TRAIL_READ_ABSENT (a genuine fresh install).
      * Every line valid, file ends with a newline -> TRAIL_READ_OK.
      * Every line valid except the last, which lacks a trailing newline
        and is a recoverable fragment -> TRAIL_READ_TRUNCATED_TAIL. The
        fragment becomes an unclosed ``started`` entry.
      * Any structurally bad line that is NOT a recoverable tail (bad
        JSON in the middle, a non-object line, a line missing a required
        field, or an unrecoverable tail fragment) -> TRAIL_READ_UNREADABLE,
        naming the 1-based line number. Every line that DID parse is
        still returned, because "I could not read line 7" is not "I could
        not read anything".

      An OSError reading the file is also UNREADABLE, never ABSENT: a
      permission error is not evidence that a user has no history.
    Inputs: path (Path) - the migration_trail.jsonl path.
    Output: TrailReadResult.
    Example: read_trail(state_dir / "migration_trail.jsonl").status == "ok"
    """
    if not path.exists():
        return TrailReadResult(status=TRAIL_READ_ABSENT)

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        return TrailReadResult(
            status=TRAIL_READ_UNREADABLE,
            error=f"could not read {path.name}: {exc}",
        )

    if not raw_bytes:
        return TrailReadResult(status=TRAIL_READ_OK, line_count=0)

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return TrailReadResult(
            status=TRAIL_READ_UNREADABLE,
            error=f"{path.name} is not valid UTF-8: {exc}",
        )

    ends_cleanly = text.endswith("\n")
    lines = text.split("\n")
    if ends_cleanly:
        lines = lines[:-1]

    entries: List[TrailEntry] = []
    last_index = len(lines) - 1
    for index, raw_line in enumerate(lines):
        line_no = index + 1
        stripped = raw_line.strip()
        if not stripped:
            continue
        parsed = _parse_line(stripped)
        if parsed is not None:
            entries.append(parsed)
            continue
        is_tail = index == last_index and not ends_cleanly
        if is_tail:
            recovered = _recover_partial_line(stripped)
            if recovered is not None:
                entries.append(recovered)
                return TrailReadResult(
                    status=TRAIL_READ_TRUNCATED_TAIL,
                    entries=entries,
                    corrupt_line_no=line_no,
                    error=(
                        f"{path.name} line {line_no} was cut off mid-write; "
                        "entry_uuid and kind were recovered and the step is "
                        "treated as interrupted"
                    ),
                    line_count=len(lines),
                )
            return TrailReadResult(
                status=TRAIL_READ_UNREADABLE,
                entries=entries,
                corrupt_line_no=line_no,
                error=(
                    f"{path.name} line {line_no} is an incomplete final line "
                    "and no entry_uuid could be recovered from it"
                ),
                line_count=len(lines),
            )
        return TrailReadResult(
            status=TRAIL_READ_UNREADABLE,
            entries=entries,
            corrupt_line_no=line_no,
            error=f"{path.name} is corrupt at line {line_no}",
            line_count=len(lines),
        )

    return TrailReadResult(
        status=TRAIL_READ_OK, entries=entries, line_count=len(lines)
    )


def _parse_line(stripped: str) -> Optional[TrailEntry]:
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for required in REQUIRED_FIELDS:
        if data.get(required) in (None, ""):
            return None
    return TrailEntry.from_dict(data)


def find_unclosed(entries: List[TrailEntry]) -> List[TrailEntry]:
    closed = {e.entry_uuid for e in entries if e.status in TRAIL_CLOSING_STATUSES}
    return [
        e
        for e in entries
        if e.status == TRAIL_STATUS_STARTED and e.entry_uuid not in closed
    ]


def prior_interrupt_uuid(
    read: TrailReadResult, started: TrailEntry
) -> Optional[str]:
    for entry in reversed(find_unclosed(read.entries)):
        if entry.entry_uuid == started.entry_uuid:
            continue
        if entry.to_version == started.to_version:
            return entry.entry_uuid
    return None

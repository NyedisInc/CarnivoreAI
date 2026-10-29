
from __future__ import annotations

import time
from typing import NamedTuple, Optional

PIPE_OWNER_OPTION: str = "@cloude_pipe_path"

FIELD_SEPARATOR: str = "|"

OWNERSHIP_FORMAT: str = (
    "#{pane_dead}"
    + FIELD_SEPARATOR
    + "#{pane_pipe}"
    + FIELD_SEPARATOR
    + "#{window_activity}"
    + FIELD_SEPARATOR
    + "#{history_size}:#{cursor_x}:#{cursor_y}"
    + FIELD_SEPARATOR
    + "#{" + PIPE_OWNER_OPTION + "}"
)

PIPE_LIVENESS_SILENCE_SECONDS: float = 5.0


OWNED: str = "owned"

PANE_DEAD: str = "pane_dead"

NO_PIPE: str = "no_pipe"

NO_OWNER_RECORDED: str = "no_owner_recorded"

FOREIGN_OWNER: str = "foreign_owner"

LEGACY_OWNER: str = "legacy_owner"

FILE_MISSING: str = "file_missing"

SILENT_WHILE_PANE_ACTIVE: str = "silent_while_pane_active"

QUIET: str = "quiet"

REISSUE_VERDICTS: frozenset = frozenset(
    {NO_PIPE, NO_OWNER_RECORDED, FOREIGN_OWNER, LEGACY_OWNER, FILE_MISSING,
     SILENT_WHILE_PANE_ACTIVE}
)

THEFT_VERDICTS: frozenset = frozenset(
    {FOREIGN_OWNER, SILENT_WHILE_PANE_ACTIVE}
)


class PaneReading(NamedTuple):

    dead: bool
    piped: bool
    activity_epoch: Optional[int]
    signature: str
    owner: str


def parse_reading(raw: str) -> Optional[PaneReading]:
    text = raw.strip("\n")
    if not text:
        return None
    parts = text.split(FIELD_SEPARATOR, 4)
    if len(parts) != 5:
        return None
    dead_raw, piped_raw, activity_raw, signature, owner = parts
    try:
        activity: Optional[int] = int(activity_raw.strip())
    except ValueError:
        activity = None
    return PaneReading(
        dead=dead_raw.strip() == "1",
        piped=piped_raw.strip() == "1",
        activity_epoch=activity,
        signature=signature.strip(),
        owner=owner.strip(),
    )


def classify_ownership(
    reading: PaneReading,
    expected_path: str,
    file_exists: bool,
    legacy_paths: frozenset = frozenset(),
) -> str:
    if reading.dead:
        return PANE_DEAD
    if not reading.piped:
        return NO_PIPE
    if not reading.owner:
        return NO_OWNER_RECORDED
    if reading.owner != expected_path:
        if reading.owner in legacy_paths:
            return LEGACY_OWNER
        return FOREIGN_OWNER
    if not file_exists:
        return FILE_MISSING
    return OWNED


class SilenceTracker:

    def __init__(
        self,
        silence_seconds: float = PIPE_LIVENESS_SILENCE_SECONDS,
        now: Optional[float] = None,
        wall_now: Optional[float] = None,
    ) -> None:
        self._silence = silence_seconds
        self._last_bytes_at: float = time.monotonic() if now is None else now
        self._last_bytes_wall: float = (
            time.time() if wall_now is None else wall_now
        )
        self._last_probe_at: Optional[float] = None
        self._last_signature: Optional[str] = None

    def note_bytes(self, now: Optional[float] = None,
                   wall_now: Optional[float] = None) -> None:
        self._last_bytes_at = time.monotonic() if now is None else now
        self._last_bytes_wall = time.time() if wall_now is None else wall_now
        self._last_signature = None

    def due(self, now: float, has_viewers: bool) -> bool:
        if not has_viewers:
            return False
        if now - self._last_bytes_at < self._silence:
            return False
        if (
            self._last_probe_at is not None
            and now - self._last_probe_at < self._silence
        ):
            return False
        return True

    def verdict(
        self,
        reading: Optional[PaneReading],
        expected_path: str,
        now: float,
        file_exists: bool = True,
        legacy_paths: frozenset = frozenset(),
    ) -> str:
        self._last_probe_at = now
        if reading is None:
            return QUIET

        ownership = classify_ownership(
            reading, expected_path, file_exists, legacy_paths
        )
        if ownership != OWNED:
            self._last_signature = None
            return ownership

        previous_signature = self._last_signature
        self._last_signature = reading.signature

        if (
            reading.activity_epoch is not None
            and reading.activity_epoch > int(self._last_bytes_wall)
        ):
            return SILENT_WHILE_PANE_ACTIVE
        if (
            previous_signature is not None
            and previous_signature != reading.signature
        ):
            return SILENT_WHILE_PANE_ACTIVE
        return QUIET

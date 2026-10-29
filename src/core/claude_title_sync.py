
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple

from src.core.transcript_contract.parsed import ParsedLine
from src.core.transcript_contract.tail import decode_window, typed_lines

CUSTOM_TITLE_RECORD_TYPE: str = "custom-title"

CUSTOM_TITLE_FIELD: str = "customTitle"

REGISTRY_USER_NAME_SOURCE: str = "user"

LAUNCH_NAME_WINDOW: timedelta = timedelta(seconds=2)

DEFAULT_TAIL_BYTES: int = 64 * 1024

ALIGN_CHUNK_BYTES: int = 8 * 1024


CUSTOM_TITLE_FOUND: str = "found"

CUSTOM_TITLE_NO_RECORD: str = "no_record"

# could not be read
CUSTOM_TITLE_UNREADABLE: str = "unreadable"


TAIL_READ_OK: str = "ok"

# could not be read
TAIL_READ_UNREADABLE: str = "unreadable"


TITLE_APPLIED: str = "applied"

TITLE_BASELINE_RECORDED: str = "baseline_recorded"

TITLE_UNCHANGED: str = "unchanged"

TITLE_NOT_MEASURED: str = "not_measured"


@dataclass(frozen=True)
class CustomTitleRead:

    status: str
    title: Optional[str] = None
    file_size: int = 0
    scanned_from: int = 0
    detail: Optional[str] = None

    @property
    def found(self) -> bool:
        return self.status == CUSTOM_TITLE_FOUND


@dataclass(frozen=True)
class TitleApplication:

    action: str
    title: Optional[str] = None
    writes_visible_title: bool = False
    detail: Optional[str] = None


@dataclass(frozen=True)
class TranscriptTailRead:

    status: str
    records: Tuple[dict, ...] = ()
    file_size: int = 0
    scanned_from: int = 0
    detail: Optional[str] = None

    @property
    def readable(self) -> bool:
        return self.status == TAIL_READ_OK

    def typed(self) -> Tuple[ParsedLine, ...]:
        return typed_lines(self.records)


def _align_to_record_start(handle, start: int, *, max_scan: int) -> Optional[int]:
    if start <= 0:
        return 0
    scanned = 0
    cursor = start
    while cursor > 0 and scanned < max_scan:
        step = min(ALIGN_CHUNK_BYTES, cursor, max_scan - scanned)
        cursor -= step
        handle.seek(cursor)
        chunk = handle.read(step)
        if not chunk:
            break
        scanned += len(chunk)
        index = chunk.rfind(b"\n")
        if index >= 0:
            return cursor + index + 1
    if cursor <= 0:
        return 0
    return None


def read_tail_records(
    path: Optional[str],
    *,
    from_offset: int = 0,
    tail_bytes: int = DEFAULT_TAIL_BYTES,
) -> TranscriptTailRead:
    if not path:
        return TranscriptTailRead(
            TAIL_READ_UNREADABLE,
            detail="no transcript path was given, so nothing was read",
        )

    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return TranscriptTailRead(
            TAIL_READ_UNREADABLE,
            detail=f"the transcript could not be measured: {exc.strerror or exc}",
        )

    nominal = max(0, min(int(from_offset or 0), size), size - max(1, int(tail_bytes)))
    nominal = min(nominal, size)
    start = nominal
    drop_first_line = False

    try:
        with open(path, "rb") as handle:
            if nominal > 0:
                aligned = _align_to_record_start(
                    handle, nominal, max_scan=max(1, int(tail_bytes))
                )
                if aligned is None:
                    drop_first_line = True
                else:
                    start = aligned
            handle.seek(start)
            window = handle.read()
    except OSError as exc:
        return TranscriptTailRead(
            TAIL_READ_UNREADABLE,
            file_size=size,
            scanned_from=start,
            detail=f"the transcript could not be read: {exc.strerror or exc}",
        )

    records = decode_window(window, drop_first_line=drop_first_line)

    return TranscriptTailRead(
        TAIL_READ_OK,
        records=records,
        file_size=size,
        scanned_from=start,
    )


def read_newest_custom_title(
    path: Optional[str],
    *,
    from_offset: int = 0,
    tail_bytes: int = DEFAULT_TAIL_BYTES,
) -> CustomTitleRead:
    read = read_tail_records(
        path, from_offset=from_offset, tail_bytes=tail_bytes
    )
    if not read.readable:
        return CustomTitleRead(
            CUSTOM_TITLE_UNREADABLE,
            file_size=read.file_size,
            scanned_from=read.scanned_from,
            detail=read.detail,
        )

    newest: Optional[str] = None
    for record in read.records:
        if record.get("type") != CUSTOM_TITLE_RECORD_TYPE:
            continue
        value = record.get(CUSTOM_TITLE_FIELD)
        if isinstance(value, str) and value.strip():
            newest = value.strip()

    if newest is None:
        return CustomTitleRead(
            CUSTOM_TITLE_NO_RECORD,
            file_size=read.file_size,
            scanned_from=read.scanned_from,
            detail=(
                "the tail of the transcript holds no custom-title "
                "record, so claude has not renamed this conversation "
                "within the window that was read"
            ),
        )

    return CustomTitleRead(
        CUSTOM_TITLE_FOUND,
        title=newest,
        file_size=read.file_size,
        scanned_from=read.scanned_from,
    )


def registry_user_title(
    record: Any, *, row_created_at: Optional[datetime]
) -> Optional[str]:
    if record is None or not record.known:
        return None
    name = (record.name or "").strip()
    since = record.name_since
    if (
        not name
        or record.name_source != REGISTRY_USER_NAME_SOURCE
        or since is None
        or record.started_at is None
        or row_created_at is None
    ):
        return None
    if since <= row_created_at or since - record.started_at < LAUNCH_NAME_WINDOW:
        return None
    return name


def decide_title_application(
    read: CustomTitleRead,
    *,
    current_title: Optional[str],
    recorded_claude_title: Optional[str],
    registry_user_title: Optional[str] = None,
    browser_rename_ordered: bool = False,
) -> TitleApplication:
    """Whether a claude-side title should move the visible one.

    Description: PURE. The whole rule lives here so the seam that calls
      it holds no policy and can be read in one screen.

      The ladder, in order:

      1. Nothing was read -> :data:`TITLE_NOT_MEASURED`. Covers both
         non-FOUND statuses; a read that did not answer decides nothing.
      2. The title equals the one already recorded ->
         :data:`TITLE_UNCHANGED`. THIS IS WHAT MAKES REPEATED EVENTS
         FREE, and it is why the same hook arriving twice writes once.
         UNLESS the visible title differs and is either empty or provably
         older than a user-set registry name (``registry_user_title``
         equals the observed name and no browser rename is ordered after
         the last agreement): then :data:`TITLE_APPLIED`. This heals a
         row whose ``/rename`` became its baseline (issue #518).
      3. Nothing was recorded before -> :data:`TITLE_BASELINE_RECORDED`.
         First sight is a baseline, never an instruction. See the module
         docstring. UNLESS the visible title is empty, or the registry
         orders the observed name after the row's creation
         (``registry_user_title`` equals it): then :data:`TITLE_APPLIED`.
      4. Otherwise the name CHANGED while we were watching ->
         :data:`TITLE_APPLIED`.
    """
    if not read.found or not read.title:
        return TitleApplication(
            TITLE_NOT_MEASURED,
            detail=read.detail or "no claude-side title was read",
        )

    observed = read.title
    recorded = (recorded_claude_title or "").strip() or None
    visible = (current_title or "").strip()
    user_set = registry_user_title is not None and registry_user_title == observed

    if recorded is not None and observed == recorded:
        if observed != visible and (
            not visible or (user_set and not browser_rename_ordered)
        ):
            return TitleApplication(
                TITLE_APPLIED,
                title=observed,
                writes_visible_title=True,
                detail=(
                    "the recorded claude-side name was never shown, and the "
                    "row's title is empty or older than the user's rename"
                ),
            )
        return TitleApplication(
            TITLE_UNCHANGED,
            detail="claude's name for this conversation has not changed",
        )

    if recorded is None:
        if not visible or user_set:
            return TitleApplication(
                TITLE_APPLIED,
                title=observed,
                writes_visible_title=(observed != visible),
                detail=(
                    "first sight of a claude-side name, applied because the "
                    "row has no title or the user set it after the row began"
                ),
            )
        return TitleApplication(
            TITLE_BASELINE_RECORDED,
            title=observed,
            detail=(
                "first sight of a claude-side name for this session, so "
                "it is recorded as the baseline and the visible title is "
                "left alone - there is no way to tell whether it predates "
                "the label the row already carries"
            ),
        )

    return TitleApplication(
        TITLE_APPLIED,
        title=observed,
        writes_visible_title=(observed != (current_title or "")),
        detail="claude renamed this conversation after we last looked",
    )

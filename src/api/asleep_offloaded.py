
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

import structlog

from src.config import settings
from src.core.backup_health import offloaded_marker
from src.core.project_history.query import is_offloaded_conversation
from src.core.project_history.transcripts import OnDiskProbe
from src.models.records import SessionRecord

logger = structlog.get_logger()

_logged_unreadable: Optional[Tuple[int, int]] = None


def _note_unreadable(state_dir: Path) -> None:
    global _logged_unreadable  # noqa: PLW0603
    try:
        stat = (state_dir / offloaded_marker.MARKER_FILE).stat()
        signature: Optional[Tuple[int, int]] = (stat.st_size, stat.st_mtime_ns)
    except OSError:
        signature = None
    if signature is not None and signature == _logged_unreadable:
        return
    _logged_unreadable = signature
    logger.error("offloaded_marker_unreadable_for_listing", state_dir=str(state_dir))


def stamp_offloaded(rows: Sequence[Mapping[str, Any]], records: Sequence[SessionRecord], state_dir: Optional[Path] = None,
                    transcripts: Any = None) -> None:
    asleep = [(row, rec) for row, rec in zip(rows, records) if rec.asleep]
    if not asleep:
        return
    folder = state_dir or Path(settings.get_state_dir())
    marker = offloaded_marker.read(folder, quiet=True)
    if marker.unreadable:
        _note_unreadable(folder)
        return
    on_disk = transcripts if transcripts is not None else OnDiskProbe()
    held = marker.rows.keys()
    for row, rec in asleep:
        rec.offloaded = is_offloaded_conversation(row.get("claude_session_uuid") or None, held, on_disk)

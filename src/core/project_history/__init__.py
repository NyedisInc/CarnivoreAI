"""The projects page's read model: every project with its session history.

CORE KEEPS ROWS, THE ARCHIVE IS A PLUGIN (issue #800). Nothing here reads
the transcript archive (``cloude-archive.db``). Whether a closed row can be
resumed is answered from the LIVE transcript corpus (``~/.claude/projects``),
the same files a resume reads; a row whose conversation id is known but
whose transcript is gone is marked so the page can offer the archive
plugin's hook instead of a resume.

Modules:
  classify     - one row's state, activity time and display title (pure).
  transcripts  - which conversation ids have a transcript on disk.
  query        - the parsed request and the grouped, paginated answer.
"""

from src.core.project_history.classify import (
    HISTORY_STATES,
    activity_at,
    display_title,
    row_state,
)
from src.core.project_history.query import (
    HistoryQuery,
    HistoryQueryError,
    build_history,
)
from src.core.project_history.transcripts import transcript_uuid_index

__all__ = [
    "HISTORY_STATES",
    "HistoryQuery",
    "HistoryQueryError",
    "activity_at",
    "build_history",
    "display_title",
    "row_state",
    "transcript_uuid_index",
]


from __future__ import annotations

from typing import Tuple

JOBS_TABLE: str = "pipeline_jobs"
STAGES_TABLE: str = "pipeline_stage_runs"

DOCS_TABLE: str = "session_search_docs"
ROWS_TABLE: str = "session_search_rows"
FTS_TABLE: str = "session_search_fts"
MIN_SQLITE: Tuple[int, int, int] = (3, 43, 0)
LIVE_TABLE: str = "session_search_live"
LIVE_ID_COLUMN: str = "live_id"
DOC_WATERMARK_COLUMNS = ("src_complete_bytes", "src_lines", "src_last_serial", "src_last_offset")

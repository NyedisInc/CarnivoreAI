
from __future__ import annotations

from typing import Tuple

DDL_ARCHIVE_PROJECT_OVERLAY = """
CREATE TABLE IF NOT EXISTS archive_project_overlay (
  identity_key   TEXT PRIMARY KEY,
  identity_kind  TEXT NOT NULL
                  CHECK (identity_kind IN ('cwd', 'project_id')),
  display_name   TEXT,
  group_name     TEXT,
  hidden         INTEGER NOT NULL DEFAULT 0
                  CHECK (hidden IN (0, 1)),
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL,
  CHECK (display_name IS NULL OR TRIM(display_name) <> ''),
  CHECK (group_name IS NULL OR TRIM(group_name) <> '')
)
"""

DDL_ARCHIVE_PROJECT_OVERLAY_GROUP_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_archive_project_overlay_group "
    "ON archive_project_overlay (group_name) "
    "WHERE group_name IS NOT NULL"
)

DDL_ARCHIVE_PROJECT_OVERLAY_HIDDEN_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_archive_project_overlay_hidden "
    "ON archive_project_overlay (hidden) "
    "WHERE hidden = 1"
)

DDL_V19: Tuple[str, ...] = (
    DDL_ARCHIVE_PROJECT_OVERLAY,
    DDL_ARCHIVE_PROJECT_OVERLAY_GROUP_INDEX,
    DDL_ARCHIVE_PROJECT_OVERLAY_HIDDEN_INDEX,
)

OVERLAY_TABLE: str = "archive_project_overlay"

ARCHIVE_TABLES_NEVER_WRITTEN: Tuple[str, ...] = (
    "message_projects",
    "message_transcripts",
    "message_bodies",
    "message_appearances",
    "message_content_blocks",
)

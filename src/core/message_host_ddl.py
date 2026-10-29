
from __future__ import annotations

from typing import Tuple


DDL_MESSAGE_HOSTS = """
CREATE TABLE IF NOT EXISTS message_hosts (
  id                 INTEGER PRIMARY KEY,
  machine_id         TEXT NOT NULL UNIQUE,
  machine_id_scheme  TEXT NOT NULL
                      CHECK (machine_id_scheme IN ('platform_uuid',
                                                   'declared')),
  display_name       TEXT NOT NULL,
  hostname           TEXT,
  platform           TEXT,
  first_seen_at      TEXT NOT NULL
)
"""


DDL_MESSAGE_CORPORA = """
CREATE TABLE IF NOT EXISTS message_corpora (
  id            INTEGER PRIMARY KEY,
  host_id       INTEGER NOT NULL REFERENCES message_hosts(id),
  corpus_key    TEXT NOT NULL,
  root_path     TEXT NOT NULL,
  manifest_sha  TEXT,
  collected_at  TEXT NOT NULL,
  UNIQUE (host_id, corpus_key)
)
"""

DDL_MESSAGE_PROJECTS = """
CREATE TABLE IF NOT EXISTS message_projects (
  id             INTEGER PRIMARY KEY,
  corpus_id      INTEGER NOT NULL REFERENCES message_corpora(id),
  slug           TEXT NOT NULL,
  observed_cwd   TEXT,
  first_seen_at  TEXT NOT NULL,
  UNIQUE (corpus_id, slug)
)
"""



ALTER_TRANSCRIPTS: Tuple[str, ...] = (
    "ALTER TABLE message_transcripts ADD COLUMN host_id INTEGER "
    "REFERENCES message_hosts(id)",
    "ALTER TABLE message_transcripts ADD COLUMN corpus_id INTEGER "
    "REFERENCES message_corpora(id)",
    "ALTER TABLE message_transcripts ADD COLUMN project_id INTEGER "
    "REFERENCES message_projects(id)",
    "ALTER TABLE message_transcripts ADD COLUMN source_path TEXT",
    "ALTER TABLE message_transcripts ADD COLUMN host_attribution TEXT",
    "ALTER TABLE message_transcripts ADD COLUMN project_attribution TEXT",
)

HOST_ATTRIBUTION_VALUES: Tuple[str, ...] = (
    "manifest_verified", "declared", "cannot_determine",
)

# could not be read
PROJECT_ATTRIBUTION_VALUES: Tuple[str, ...] = (
    "derived", "none_declared", "cannot_determine",
)



DDL_IX_TRANSCRIPTS_HOST = (
    "CREATE INDEX IF NOT EXISTS ix_message_transcripts_host "
    "ON message_transcripts (host_id)"
)

DDL_IX_TRANSCRIPTS_PROJECT = (
    "CREATE INDEX IF NOT EXISTS ix_message_transcripts_project "
    "ON message_transcripts (project_id)"
)

DDL_UX_TRANSCRIPTS_CORPUS_PATH = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_message_transcripts_corpus_path "
    "ON message_transcripts (corpus_id, source_path)"
)

DDL_IX_PROJECTS_SLUG = (
    "CREATE INDEX IF NOT EXISTS ix_message_projects_slug "
    "ON message_projects (slug)"
)



DDL_VIEW_BODY_HOSTS = """
CREATE VIEW IF NOT EXISTS message_body_hosts AS
SELECT DISTINCT a.body_id AS body_id, t.host_id AS host_id
  FROM message_appearances a
  JOIN message_transcripts t ON t.id = a.transcript_id
 WHERE a.body_id IS NOT NULL AND t.host_id IS NOT NULL
"""

DDL_VIEW_SESSION_HOSTS = """
CREATE VIEW IF NOT EXISTS message_session_hosts AS
SELECT session_ref            AS session_ref,
       session_ref_scheme     AS session_ref_scheme,
       COUNT(DISTINCT host_id) AS host_count,
       COUNT(*)               AS transcript_count
  FROM message_transcripts
 WHERE host_id IS NOT NULL
 GROUP BY session_ref, session_ref_scheme
"""


DDL_V17: Tuple[str, ...] = (
    DDL_MESSAGE_HOSTS,
    DDL_MESSAGE_CORPORA,
    DDL_MESSAGE_PROJECTS,
) + ALTER_TRANSCRIPTS + (
    DDL_IX_TRANSCRIPTS_HOST,
    DDL_IX_TRANSCRIPTS_PROJECT,
    DDL_UX_TRANSCRIPTS_CORPUS_PATH,
    DDL_IX_PROJECTS_SLUG,
    DDL_VIEW_BODY_HOSTS,
    DDL_VIEW_SESSION_HOSTS,
)

V17_TABLE_NAMES: Tuple[str, ...] = (
    "message_hosts",
    "message_corpora",
    "message_projects",
)

V17_TRANSCRIPT_COLUMNS: Tuple[str, ...] = (
    "host_id", "corpus_id", "project_id", "source_path",
    "host_attribution", "project_attribution",
)

V17_VIEW_NAMES: Tuple[str, ...] = (
    "message_body_hosts", "message_session_hosts",
)

"""DDL for schema v16: the message identity / appearance model.

So the model splits a message in two:

  ``message_bodies``       one row per DISTINCT BODY, keyed by
                           (uuid, sha256-of-body). Two different bodies
                           under one uuid are two rows, never a merge and
                           never a keep-first - losing either is data
                           loss, and it is a real case: an independent
                           re-measurement here of 3,443 duplicate-uuid
                           groups that had raw JSON on both sides found
                           39 (1.13%) with genuinely different bodies.
  ``message_appearances``  one row per (transcript, line). Holds
                           seq_in_file, is_sidechain, agent_id, the
                           envelope values, the ORIGINAL top-level key
                           order, and the sha256 of the original line.
                           This is where the subagent linkage stops being
                           an implicit near-duplicate row and becomes an
                           explicit, queryable edge.

NOTHING IS DROPPED BECAUSE IT FAILS TO PARSE OR TO LINK. A blank line and
a line whose JSON does not parse both get an appearance row (with
``line_status`` saying which, ``body_id`` NULL and ``raw_line`` holding
the bytes), because byte-exact export of the whole transcript depends on
them and because "we could not parse it" is not a reason to discard it.

ADDITIVE ONLY, like every step before it: eight CREATE TABLE and nine
CREATE INDEX statements, each carrying its own IF NOT EXISTS. No existing
table is altered, no column added to one, nothing dropped, renamed or
retyped.
"""

from __future__ import annotations

from typing import Tuple


DDL_MESSAGE_RECORD_TYPES = """
CREATE TABLE IF NOT EXISTS message_record_types (
  id     INTEGER PRIMARY KEY,
  value  TEXT NOT NULL UNIQUE
)
"""

DDL_MESSAGE_ROLES = """
CREATE TABLE IF NOT EXISTS message_roles (
  id     INTEGER PRIMARY KEY,
  value  TEXT NOT NULL UNIQUE
)
"""

DDL_MESSAGE_MODELS = """
CREATE TABLE IF NOT EXISTS message_models (
  id     INTEGER PRIMARY KEY,
  value  TEXT NOT NULL UNIQUE
)
"""

DDL_MESSAGE_COMPACT_SUBTYPES = """
CREATE TABLE IF NOT EXISTS message_compact_subtypes (
  id     INTEGER PRIMARY KEY,
  value  TEXT NOT NULL UNIQUE
)
"""

LOOKUP_TABLES: Tuple[Tuple[str, str], ...] = (
    ("message_record_types", DDL_MESSAGE_RECORD_TYPES),
    ("message_roles", DDL_MESSAGE_ROLES),
    ("message_models", DDL_MESSAGE_MODELS),
    ("message_compact_subtypes", DDL_MESSAGE_COMPACT_SUBTYPES),
)



DDL_MESSAGE_TRANSCRIPTS = """
CREATE TABLE IF NOT EXISTS message_transcripts (
  id                    INTEGER PRIMARY KEY,
  source_ref            TEXT NOT NULL UNIQUE,
  session_ref           TEXT NOT NULL,
  session_ref_scheme    TEXT NOT NULL
                         CHECK (session_ref_scheme IN ('uuid', 'agent', 'opaque')),
  line_ending           TEXT NOT NULL
                         CHECK (line_ending IN ('LF', 'CRLF', 'MIXED', 'NONE')),
  has_trailing_newline  INTEGER NOT NULL
                         CHECK (has_trailing_newline IN (0, 1)),
  line_count            INTEGER NOT NULL DEFAULT 0,
  content_sha256        TEXT NOT NULL,
  raw_byte_length       INTEGER NOT NULL,
  ingested_at           TEXT NOT NULL,
  newest_message_ts     TEXT
)
"""



DDL_MESSAGE_BODIES = """
CREATE TABLE IF NOT EXISTS message_bodies (
  id                    INTEGER PRIMARY KEY,
  identity_key          TEXT NOT NULL UNIQUE,
  message_uuid          TEXT,
  body_sha256           TEXT NOT NULL,
  body_bytes_sha256     TEXT NOT NULL,
  body_json             TEXT NOT NULL,
  record_type_id        INTEGER REFERENCES message_record_types(id),
  role_id               INTEGER REFERENCES message_roles(id),
  model_id              INTEGER REFERENCES message_models(id),
  compact_subtype_id    INTEGER REFERENCES message_compact_subtypes(id),
  parent_uuid           TEXT,
  ts                    TEXT,
  origin_session_ref    TEXT,
  is_compact_boundary   INTEGER NOT NULL DEFAULT 0,
  secret_finding_count  INTEGER NOT NULL DEFAULT 0,
  first_seen_at         TEXT NOT NULL
)
"""



DDL_MESSAGE_APPEARANCES = """
CREATE TABLE IF NOT EXISTS message_appearances (
  id                 INTEGER PRIMARY KEY,
  transcript_id      INTEGER NOT NULL
                      REFERENCES message_transcripts(id) ON DELETE CASCADE,
  line_no            INTEGER NOT NULL,
  seq_in_file        INTEGER,
  line_status        TEXT NOT NULL
                      CHECK (line_status IN ('ok', 'blank', 'invalid_json')),
  body_id            INTEGER REFERENCES message_bodies(id),
  envelope_json      TEXT,
  key_order_json     TEXT,
  serializer_style   TEXT,
  line_sha256        TEXT NOT NULL,
  line_byte_length   INTEGER NOT NULL,
  raw_line           TEXT,
  fidelity_outcome   TEXT NOT NULL
                      CHECK (fidelity_outcome IN
                             ('fidelity_verified', 'fidelity_failed',
                              'fidelity_unverifiable')),
  is_sidechain       INTEGER NOT NULL DEFAULT 0,
  agent_id           TEXT,
  UNIQUE (transcript_id, line_no)
)
"""



DDL_MESSAGE_INGEST_FINDINGS = """
CREATE TABLE IF NOT EXISTS message_ingest_findings (
  id              INTEGER PRIMARY KEY,
  observed_at     TEXT NOT NULL,
  condition_code  TEXT NOT NULL,
  severity        TEXT NOT NULL CHECK (severity IN ('stop', 'advisory')),
  subject_kind    TEXT NOT NULL
                   CHECK (subject_kind IN ('transcript', 'body', 'appearance')),
  subject_id      INTEGER NOT NULL,
  detail          TEXT NOT NULL
)
"""

DDL_MESSAGE_SECRET_FINDINGS = """
CREATE TABLE IF NOT EXISTS message_secret_findings (
  id            INTEGER PRIMARY KEY,
  body_id       INTEGER NOT NULL
                 REFERENCES message_bodies(id) ON DELETE CASCADE,
  detector      TEXT NOT NULL,
  match_offset  INTEGER NOT NULL,
  match_length  INTEGER NOT NULL,
  value_sha256  TEXT NOT NULL,
  observed_at   TEXT NOT NULL
)
"""



DDL_IX_MESSAGE_BODIES_UUID = (
    "CREATE INDEX IF NOT EXISTS ix_message_bodies_uuid "
    "ON message_bodies (message_uuid)"
)

DDL_IX_MESSAGE_BODIES_SHA = (
    "CREATE INDEX IF NOT EXISTS ix_message_bodies_sha "
    "ON message_bodies (body_sha256)"
)

DDL_IX_MESSAGE_BODIES_PARENT = (
    "CREATE INDEX IF NOT EXISTS ix_message_bodies_parent "
    "ON message_bodies (parent_uuid)"
)

DDL_IX_MESSAGE_APPEARANCES_BODY = (
    "CREATE INDEX IF NOT EXISTS ix_message_appearances_body "
    "ON message_appearances (body_id)"
)

DDL_IX_MESSAGE_APPEARANCES_AGENT = (
    "CREATE INDEX IF NOT EXISTS ix_message_appearances_agent "
    "ON message_appearances (agent_id)"
)

DDL_IX_MESSAGE_TRANSCRIPTS_SESSION = (
    "CREATE INDEX IF NOT EXISTS ix_message_transcripts_session "
    "ON message_transcripts (session_ref)"
)

DDL_IX_MESSAGE_INGEST_FINDINGS_CODE = (
    "CREATE INDEX IF NOT EXISTS ix_message_ingest_findings_code "
    "ON message_ingest_findings (condition_code)"
)

DDL_IX_MESSAGE_INGEST_FINDINGS_SUBJECT = (
    "CREATE INDEX IF NOT EXISTS ix_message_ingest_findings_subject "
    "ON message_ingest_findings (subject_kind, subject_id)"
)

DDL_IX_MESSAGE_SECRET_FINDINGS_BODY = (
    "CREATE INDEX IF NOT EXISTS ix_message_secret_findings_body "
    "ON message_secret_findings (body_id)"
)


DDL_V16: Tuple[str, ...] = (
    DDL_MESSAGE_RECORD_TYPES,
    DDL_MESSAGE_ROLES,
    DDL_MESSAGE_MODELS,
    DDL_MESSAGE_COMPACT_SUBTYPES,
    DDL_MESSAGE_TRANSCRIPTS,
    DDL_MESSAGE_BODIES,
    DDL_MESSAGE_APPEARANCES,
    DDL_MESSAGE_INGEST_FINDINGS,
    DDL_MESSAGE_SECRET_FINDINGS,
    DDL_IX_MESSAGE_BODIES_UUID,
    DDL_IX_MESSAGE_BODIES_SHA,
    DDL_IX_MESSAGE_BODIES_PARENT,
    DDL_IX_MESSAGE_APPEARANCES_BODY,
    DDL_IX_MESSAGE_APPEARANCES_AGENT,
    DDL_IX_MESSAGE_TRANSCRIPTS_SESSION,
    DDL_IX_MESSAGE_INGEST_FINDINGS_CODE,
    DDL_IX_MESSAGE_INGEST_FINDINGS_SUBJECT,
    DDL_IX_MESSAGE_SECRET_FINDINGS_BODY,
)

V16_TABLE_NAMES: Tuple[str, ...] = (
    "message_record_types",
    "message_roles",
    "message_models",
    "message_compact_subtypes",
    "message_transcripts",
    "message_bodies",
    "message_appearances",
    "message_ingest_findings",
    "message_secret_findings",
)

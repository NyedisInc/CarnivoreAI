
from __future__ import annotations

from typing import Tuple

CURRENT_SCHEMA_VERSION: int = 102

META_SCHEMA_VERSION = "schema_version"
META_CREATED_AT = "created_at"
META_INSTALL_ID = "install_id"

TRAIL_KINDS: Tuple[str, ...] = ("bootstrap", "config", "schema", "import", "code")

META_IMPORTED_FROM_JSON_AT = "imported_from_json_at"
META_IMPORTED_FROM_JSON_RESULT = "imported_from_json_result"

PROJECT_SOURCE_CONFIG_IMPORT = "config_import"
PROJECT_SOURCE_USER = "user"
PROJECT_SOURCE_ADOPTION = "adoption"
PROJECT_SOURCE_TRANSCRIPT_IMPORT = "transcript_import"
PROJECT_SOURCES: Tuple[str, ...] = (
    PROJECT_SOURCE_CONFIG_IMPORT,
    PROJECT_SOURCE_USER,
    PROJECT_SOURCE_ADOPTION,
    PROJECT_SOURCE_TRANSCRIPT_IMPORT,
)

PROJECT_PRESENCE_PRESENT = "present"
PROJECT_PRESENCE_MISSING = "missing"
PROJECT_PRESENCE_UNREACHABLE = "unreachable"
PROJECT_PRESENCE_UNCHECKED = "unchecked"
PROJECT_PRESENCE_STATES: Tuple[str, ...] = (
    PROJECT_PRESENCE_PRESENT,
    PROJECT_PRESENCE_MISSING,
    PROJECT_PRESENCE_UNREACHABLE,
    PROJECT_PRESENCE_UNCHECKED,
)

TRAIL_STATUS_STARTED = "started"
TRAIL_STATUS_COMPLETED = "completed"
TRAIL_STATUS_FAILED = "failed"
TRAIL_STATUS_INTERRUPTED = "interrupted"
TRAIL_STATUS_COMPLETED_AFTER_INTERRUPT = "completed_after_interrupt"

TRAIL_STATUSES: Tuple[str, ...] = (
    TRAIL_STATUS_STARTED,
    TRAIL_STATUS_COMPLETED,
    TRAIL_STATUS_FAILED,
    TRAIL_STATUS_INTERRUPTED,
    TRAIL_STATUS_COMPLETED_AFTER_INTERRUPT,
)

TRAIL_CLOSING_STATUSES: Tuple[str, ...] = (
    TRAIL_STATUS_COMPLETED,
    TRAIL_STATUS_FAILED,
    TRAIL_STATUS_INTERRUPTED,
    TRAIL_STATUS_COMPLETED_AFTER_INTERRUPT,
)



SESSION_ORIGIN_CREATED = "created"
SESSION_ORIGIN_ADOPTED = "adopted"
SESSION_ORIGIN_OBSERVED = "observed"
SESSION_ORIGIN_IMPORTED = "imported"
SESSION_ORIGINS: Tuple[str, ...] = (
    SESSION_ORIGIN_CREATED,
    SESSION_ORIGIN_ADOPTED,
    SESSION_ORIGIN_OBSERVED,
    SESSION_ORIGIN_IMPORTED,
)

SESSION_OWNED_ORIGINS: Tuple[str, ...] = (
    SESSION_ORIGIN_CREATED,
    SESSION_ORIGIN_ADOPTED,
)

SESSION_LIFECYCLE_RUNNING = "running"
SESSION_LIFECYCLE_STOPPED = "stopped"
SESSION_LIFECYCLE_UNKNOWN = "unknown"
SESSION_LIFECYCLES: Tuple[str, ...] = (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_LIFECYCLE_UNKNOWN,
)

SESSION_LIFECYCLE_SOURCE_TMUX_LIST = "tmux_list"
SESSION_LIFECYCLE_SOURCE_PROBE_FAILED = "probe_failed"
SESSION_LIFECYCLE_SOURCE_TMUX_MISSING = "tmux_missing"
SESSION_LIFECYCLE_SOURCE_IMPORT = "import"

SESSION_ATTRIBUTION_EXPLICIT = "explicit"
SESSION_ATTRIBUTION_DERIVED_DEEPEST = "derived_deepest"
SESSION_ATTRIBUTION_NONE = "none"
SESSION_ATTRIBUTION_UNKNOWN = "unknown"
SESSION_ATTRIBUTIONS: Tuple[str, ...] = (
    SESSION_ATTRIBUTION_EXPLICIT,
    SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    SESSION_ATTRIBUTION_NONE,
    SESSION_ATTRIBUTION_UNKNOWN,
)

SESSION_FAMILY_SOURCE_WRAPPER = "wrapper"
SESSION_FAMILY_SOURCE_RESERVED_NAME = "reserved_name"
SESSION_FAMILY_SOURCE_FINGERPRINT = "fingerprint"
SESSION_FAMILY_SOURCE_LAUNCHED = "launched"

SESSION_FAMILY_SOURCE_NOT_LAUNCHED = "not_launched"

SESSION_FAMILY_SOURCE_INFERRED_PROCESS = "inferred_process"

SESSION_FAMILY_SOURCE_UNKNOWN = "unknown"

SESSION_CLAUDE_UUID_SOURCE_HOOK = "hook"
SESSION_CLAUDE_UUID_SOURCE_REGISTRY = "registry"
SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV = "correlated_argv"
SESSION_CLAUDE_UUID_SOURCE_CORRELATED = "correlated"

SESSION_CLAUDE_UUID_SOURCE_CODEX_THREAD_MAP = "codex_thread_map"

SESSION_CLAUDE_UUID_SOURCE_BOOKMARK_REWIND = "bookmark_rewind"

SESSION_CLAUDE_UUID_SOURCES: Tuple[str, ...] = (
    SESSION_CLAUDE_UUID_SOURCE_HOOK,
    SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
    SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV,
    SESSION_CLAUDE_UUID_SOURCE_CORRELATED,
    SESSION_CLAUDE_UUID_SOURCE_CODEX_THREAD_MAP,
    SESSION_CLAUDE_UUID_SOURCE_BOOKMARK_REWIND,
)

DEFAULT_TMUX_SOCKET = "cloude"

META_SESSION_IMPORT_PENDING_REASON = "session_import_pending_reason"


DDL_META = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
)
"""

DDL_MIGRATION_TRAIL = """
CREATE TABLE IF NOT EXISTS migration_trail (
  id               INTEGER PRIMARY KEY,
  entry_uuid       TEXT NOT NULL UNIQUE,
  kind             TEXT NOT NULL,
  from_version     TEXT,
  to_version       TEXT,
  status           TEXT NOT NULL,
  started_at       TEXT NOT NULL,
  completed_at     TEXT,
  backup_path      TEXT,
  backup_verified  INTEGER,
  app_version      TEXT,
  error            TEXT,
  detail           TEXT
)
"""

DDL_MIGRATION_TRAIL_KIND_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_migration_trail_kind "
    "ON migration_trail (kind)"
)

DDL_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
  id                  INTEGER PRIMARY KEY,
  root                TEXT NOT NULL UNIQUE,
  raw_path            TEXT NOT NULL,
  display_name        TEXT NOT NULL,
  description         TEXT,
  default_agent_type  TEXT,
  source              TEXT NOT NULL,
  presence            TEXT NOT NULL DEFAULT 'unchecked',
  presence_checked_at TEXT,
  presence_detail     TEXT,
  archived_at         TEXT,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
)
"""

DDL_V1: Tuple[str, ...] = (
    DDL_META,
    DDL_MIGRATION_TRAIL,
    DDL_MIGRATION_TRAIL_KIND_INDEX,
    DDL_PROJECTS,
)

REVERSAL_SQL_V1: Tuple[str, ...] = (
    "DROP TABLE IF EXISTS projects",
    "DROP INDEX IF EXISTS ix_migration_trail_kind",
    "DROP TABLE IF EXISTS migration_trail",
    "DROP TABLE IF EXISTS meta",
)


DDL_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
  id                    INTEGER PRIMARY KEY,
  session_uuid          TEXT NOT NULL UNIQUE,

  project_id            INTEGER REFERENCES projects(id),
  project_attribution   TEXT NOT NULL DEFAULT 'unknown',
  working_dir           TEXT,

  tmux_socket           TEXT NOT NULL DEFAULT 'cloude',
  tmux_name             TEXT,
  tmux_created_epoch    INTEGER,

  origin                TEXT NOT NULL,
  adopted_at            TEXT,
  legacy_session_id     TEXT,

  agent_type            TEXT,
  agent_family          TEXT,
  agent_family_source   TEXT NOT NULL DEFAULT 'unknown',
  model                 TEXT,

  claude_session_uuid   TEXT,
  -- HOW claude_session_uuid WAS LEARNED. 'hook' (Claude Code told us,
  -- via SessionStart), 'registry' (read out of Claude Code's own session
  -- registry file and joined by tmux session name - also Claude Code
  -- reporting its own id, over a channel that repeats instead of firing
  -- once), 'correlated_argv' (read from the pane's own process argv -
  -- --resume <uuid> - at adopt time, a direct read) or 'correlated'
  -- (inferred from filesystem transcript timing at adopt time when no
  -- argv was available - the weakest of the four). NULL alongside a NULL
  -- uuid means none of the four has ever run for this row. See
  -- db_models.py's SESSION_CLAUDE_UUID_SOURCE_* block.
  claude_session_uuid_source TEXT,
  parent_session_id     INTEGER REFERENCES sessions(id),
  fork_kind             TEXT,

  lifecycle             TEXT NOT NULL DEFAULT 'unknown',
  lifecycle_checked_at  TEXT,
  lifecycle_source      TEXT,
  last_seen_running_at  TEXT,

  archived_at           TEXT,
  pinned_theme          TEXT,
  -- RETIRED (2026-09-22, all-audio removal). Nothing in src/ reads or
  -- writes this column any more. It stays because dropping a column in
  -- SQLite means rebuilding the whole `sessions` table, which is where
  -- every session's identity, project binding and conversation uuid
  -- live - real data-loss risk to retire inert bytes. See
  -- `_V9_CARRY_FORWARD` for the historical repair list, which is
  -- likewise left untouched.
  audio_enabled         INTEGER,
  unread_auto           INTEGER NOT NULL DEFAULT 0,
  unread_manual         INTEGER NOT NULL DEFAULT 0,
  -- TWO NAMES, TWO OWNERS. `title` is the USER's label (v9 made it so).
  -- `claude_title` is whatever Claude Code currently calls the session on
  -- its own side, arriving on the SessionStart payload as `session_title`.
  -- They were one column until v10, which meant Claude's auto-generated
  -- name could become the user's displayed label, a user rename silently
  -- discarded Claude's, and - because the write was guarded write-once to
  -- stop exactly that - a LATER Claude-side /rename could never land.
  -- One field cannot hold two authorities. `claude_title` is free to
  -- change as often as Claude changes it; `title` changes only when the
  -- user says so.
  title                 TEXT,
  claude_title          TEXT,
  -- DURABLE ACTIVITY STATUS. The hook-derived state used to live only in
  -- SessionActivityTracker, an in-memory dict, so a server restart forgot
  -- what every session was doing. That is worse than it sounds here: the
  -- fallback is the tmux tier, and under this app's launch path
  -- pane_current_command is a CONSTANT, so a session whose state was
  -- forgotten reports `idle` forever and is indistinguishable from one
  -- genuinely sitting at a prompt.
  -- `activity_state_at` is what makes the value judgeable rather than
  -- merely present: a state with no timestamp cannot be told apart from a
  -- stale one, and a stale `working` is a lie about right now.
  activity_state        TEXT,
  activity_state_at     TEXT,
  -- WHEN WORK LAST HAPPENED IN THIS SESSION. Stamped ONLY from a Claude
  -- Code hook event that represents the conversation doing something
  -- (see claude_hooks.WORK_EVENTS): a prompt submitted, a tool called, a
  -- subagent run, a turn stopped, a permission asked for.
  --
  -- IT IS NOT AN "OPENED" TIME AND MUST NEVER BECOME ONE. Attaching to a
  -- session, selecting it in the sidebar, deep-linking to it or
  -- re-binding it after a server restart all leave this column alone.
  -- That is the entire reason it exists: the session list is read as a
  -- TIMELINE of what has been worked on, and a list that reshuffles when
  -- you merely look at a row destroys the recall it is read for.
  --
  -- IT IS NOT `updated_at` AND NOT `activity_state_at`. `updated_at` is
  -- written by unrelated bookkeeping, including a restart's rebind, so a
  -- restart would read as work. `activity_state_at` is written by the
  -- LISTING path too, whenever a settled state changes - including the
  -- working -> idle expiry, which is a session going quiet, not a
  -- session working.
  --
  -- NULL means NO WORK HAS BEEN RECORDED, which is a third outcome and
  -- not a zero: such a row sorts BELOW every row that has a value,
  -- in its own stable order, and is labelled as such in the UI rather
  -- than blended in at the bottom of the worked rows.
  last_work_at          TEXT,

  created_at            TEXT NOT NULL,
  updated_at            TEXT NOT NULL
)
"""

DDL_SESSIONS_INSTANCE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sessions_tmux_instance "
    "ON sessions (tmux_socket, tmux_name, tmux_created_epoch) "
    "WHERE tmux_name IS NOT NULL AND tmux_created_epoch IS NOT NULL"
)

DDL_SESSIONS_PROJECT_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_sessions_project ON sessions (project_id)"
)

DDL_SESSIONS_LIFECYCLE_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_sessions_lifecycle ON sessions (lifecycle)"
)

DDL_SESSIONS_PARENT_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_sessions_parent "
    "ON sessions (parent_session_id) WHERE parent_session_id IS NOT NULL"
)

DDL_V2: Tuple[str, ...] = (
    DDL_SESSIONS,
    DDL_SESSIONS_INSTANCE_INDEX,
    DDL_SESSIONS_PROJECT_INDEX,
    DDL_SESSIONS_LIFECYCLE_INDEX,
    DDL_SESSIONS_PARENT_INDEX,
)

DDL_SESSIONS_ADD_SESSION_ID = (
    "ALTER TABLE sessions ADD COLUMN tmux_session_id TEXT"
)

DDL_V3: Tuple[str, ...] = (DDL_SESSIONS_ADD_SESSION_ID,)

REVERSAL_SQL_V3: Tuple[str, ...] = ()

DDL_PROJECTS_ADD_LAST_OPENED_AT = (
    "ALTER TABLE projects ADD COLUMN last_opened_at TEXT"
)

DDL_V4: Tuple[str, ...] = (DDL_PROJECTS_ADD_LAST_OPENED_AT,)

REVERSAL_SQL_V4: Tuple[str, ...] = ()


DDL_PROJECT_TOMBSTONES = """
CREATE TABLE IF NOT EXISTS project_tombstones (
  root         TEXT PRIMARY KEY,
  display_name TEXT,
  deleted_at   TEXT NOT NULL
)
"""

META_PROJECT_TOMBSTONES_SINCE = "project_tombstones_since"

META_PROJECT_TOMBSTONES_LEGACY_GAP = "project_tombstones_legacy_gap"

META_PROJECT_RECONCILE_UNDETERMINED = "project_reconcile_undetermined_roots"

META_PROJECT_RECONCILE_LAST = "project_reconcile_last"

DDL_V5: Tuple[str, ...] = (DDL_PROJECT_TOMBSTONES,)

REVERSAL_SQL_V5: Tuple[str, ...] = ("DROP TABLE IF EXISTS project_tombstones",)


REVERSAL_SQL_V2: Tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_sessions_parent",
    "DROP INDEX IF EXISTS ix_sessions_lifecycle",
    "DROP INDEX IF EXISTS ix_sessions_project",
    "DROP INDEX IF EXISTS ux_sessions_tmux_instance",
    "DROP TABLE IF EXISTS sessions",
)

DDL_SESSIONS_ADD_USER_DECLINED_AT = (
    "ALTER TABLE sessions ADD COLUMN user_declined_at TEXT"
)

DDL_V6: Tuple[str, ...] = (DDL_SESSIONS_ADD_USER_DECLINED_AT,)

REVERSAL_SQL_V6: Tuple[str, ...] = ()

META_SESSION_IMPORT_UNATTRIBUTED = "session_import_unattributed"

DDL_SESSIONS_CLAUDE_UUID_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_sessions_claude_uuid "
    "ON sessions (claude_session_uuid) "
    "WHERE claude_session_uuid IS NOT NULL"
)

DDL_V7: Tuple[str, ...] = (DDL_SESSIONS_CLAUDE_UUID_INDEX,)

REVERSAL_SQL_V7: Tuple[str, ...] = ("DROP INDEX IF EXISTS ix_sessions_claude_uuid",)

SESSION_FORK_KIND_FORK = "fork"
SESSION_FORK_KIND_CLEAR = "clear"
SESSION_FORK_KIND_COMPACT = "compact"

SESSION_FORK_KIND_BACKGROUND = "background"

SESSION_FORK_KIND_UNKNOWN = "unknown"

SESSION_FORK_KIND_SPAWN = "spawn"

SESSION_FORK_KINDS: Tuple[str, ...] = (
    SESSION_FORK_KIND_FORK,
    SESSION_FORK_KIND_BACKGROUND,
    SESSION_FORK_KIND_CLEAR,
    SESSION_FORK_KIND_COMPACT,
    SESSION_FORK_KIND_UNKNOWN,
)

META_STAGE_A_BOUNDARY_EPOCH = "stage_a_origin_marker_boundary_epoch"



DDL_SESSIONS_CLAUDE_UUID_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_sessions_claude_uuid "
    "ON sessions (claude_session_uuid) "
    "WHERE claude_session_uuid IS NOT NULL"
)

DDL_V7: Tuple[str, ...] = (DDL_SESSIONS_CLAUDE_UUID_INDEX,)

REVERSAL_SQL_V7: Tuple[str, ...] = ("DROP INDEX IF EXISTS ix_sessions_claude_uuid",)


DDL_SESSION_GROUPS = """
CREATE TABLE IF NOT EXISTS session_groups (
  id         INTEGER PRIMARY KEY,
  group_uuid TEXT NOT NULL UNIQUE,
  name       TEXT NOT NULL,
  position   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT
)
"""

DDL_SESSION_GROUP_MEMBERS = """
CREATE TABLE IF NOT EXISTS session_group_members (
  tmux_name  TEXT PRIMARY KEY,
  group_id   INTEGER NOT NULL REFERENCES session_groups(id) ON DELETE CASCADE,
  added_at   TEXT NOT NULL
)
"""

DDL_SESSION_GROUPS_POSITION_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_session_groups_position "
    "ON session_groups (position)"
)

DDL_SESSION_GROUP_MEMBERS_GROUP_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_session_group_members_group "
    "ON session_group_members (group_id)"
)

DDL_V8: Tuple[str, ...] = (
    DDL_SESSION_GROUPS,
    DDL_SESSION_GROUP_MEMBERS,
    DDL_SESSION_GROUPS_POSITION_INDEX,
    DDL_SESSION_GROUP_MEMBERS_GROUP_INDEX,
)

REVERSAL_SQL_V8: Tuple[str, ...] = (
    "DROP TABLE IF EXISTS session_group_members",
    "DROP TABLE IF EXISTS session_groups",
)

SESSION_GROUP_NAME_MAX = 40

SESSION_GROUP_MAX = 50


REVERSAL_DESTROYS: dict = {
    1: (
        "meta (whole table)",
        "migration_trail (whole table)",
        "projects (whole table)",
    ),
    2: ("sessions (whole table)",),
    3: ("sessions.tmux_session_id",),
    5: ("project_tombstones (whole table)",),
    6: ("sessions.user_declined_at",),
    7: (),
    8: (
        "session_groups (whole table)",
        "session_group_members (whole table)",
    ),
}


DDL_SESSIONS_CLAUDE_UUID_UNIQUE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sessions_claude_uuid "
    "ON sessions (claude_session_uuid) "
    "WHERE claude_session_uuid IS NOT NULL"
)

DDL_SESSIONS_CLAUDE_UUID_PLAIN_INDEX_DROP = (
    "DROP INDEX IF EXISTS ix_sessions_claude_uuid"
)

META_SESSIONS_CLAUDE_UUID_DUPLICATES = "sessions_claude_uuid_duplicates_v12"


DDL_TRANSCRIPT_ARCHIVES = """
CREATE TABLE IF NOT EXISTS transcript_archives (
  id                         INTEGER PRIMARY KEY,
  archive_uuid               TEXT NOT NULL UNIQUE,
  kind                       TEXT NOT NULL
                              CHECK (kind IN ('session', 'subagent')),
  source_path                TEXT NOT NULL,
  content_gzip                BLOB NOT NULL,
  content_sha256             TEXT NOT NULL,
  raw_byte_length            INTEGER NOT NULL,
  compressed_byte_length     INTEGER NOT NULL,
  line_ending                TEXT NOT NULL
                              CHECK (line_ending IN
                                     ('LF', 'CRLF', 'MIXED', 'NONE')),
  has_trailing_newline       INTEGER NOT NULL
                              CHECK (has_trailing_newline IN (0, 1)),
  trailing_blank_line_count  INTEGER NOT NULL DEFAULT 0,
  record_count               INTEGER NOT NULL DEFAULT 0,
  invalid_json_line_count    INTEGER NOT NULL DEFAULT 0,
  claude_session_uuid        TEXT,
  root_state                 TEXT NOT NULL DEFAULT 'unrooted'
                              CHECK (root_state IN
                                     ('unrooted', 'rooted', 'orphaned')),
  root_session_id            INTEGER
                              REFERENCES sessions(id),
  parent_archive_id          INTEGER
                              REFERENCES transcript_archives(id),
  ingested_at                TEXT NOT NULL,
  ingest_source_mtime        TEXT,
  rooted_at                  TEXT,
  rooted_by                  TEXT
)
"""

DDL_TRANSCRIPT_RECORDS = """
CREATE TABLE IF NOT EXISTS transcript_records (
  id               INTEGER PRIMARY KEY,
  archive_id        INTEGER NOT NULL
                    REFERENCES transcript_archives(id) ON DELETE CASCADE,
  line_no          INTEGER NOT NULL,
  byte_offset      INTEGER NOT NULL,
  byte_length      INTEGER NOT NULL,
  status           TEXT NOT NULL
                    CHECK (status IN ('ok', 'invalid_json', 'blank')),
  record_type      TEXT,
  record_uuid      TEXT,
  parent_uuid      TEXT,
  ts               TEXT,
  UNIQUE (archive_id, line_no)
)
"""

DDL_TRANSCRIPT_ROOT_DECISIONS = """
CREATE TABLE IF NOT EXISTS transcript_root_decisions (
  id                  INTEGER PRIMARY KEY,
  archive_id           INTEGER NOT NULL
                       REFERENCES transcript_archives(id),
  decided_at          TEXT NOT NULL,
  decided_by          TEXT NOT NULL,
  action              TEXT NOT NULL
                       CHECK (action IN ('rooted', 'orphaned', 'reopened')),
  root_session_id     INTEGER,
  parent_archive_id   INTEGER,
  note                TEXT
)
"""

DDL_TRANSCRIPT_ARCHIVES_ROOT_STATE_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_transcript_archives_root_state "
    "ON transcript_archives (root_state)"
)

DDL_TRANSCRIPT_ARCHIVES_CLAUDE_UUID_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_transcript_archives_claude_uuid "
    "ON transcript_archives (claude_session_uuid)"
)

DDL_TRANSCRIPT_ARCHIVES_PARENT_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_transcript_archives_parent "
    "ON transcript_archives (parent_archive_id)"
)

DDL_TRANSCRIPT_RECORDS_UUID_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_transcript_records_uuid "
    "ON transcript_records (record_uuid)"
)

DDL_TRANSCRIPT_ROOT_DECISIONS_ARCHIVE_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_transcript_root_decisions_archive "
    "ON transcript_root_decisions (archive_id)"
)

DDL_V14: Tuple[str, ...] = (
    DDL_TRANSCRIPT_ARCHIVES,
    DDL_TRANSCRIPT_RECORDS,
    DDL_TRANSCRIPT_ROOT_DECISIONS,
    DDL_TRANSCRIPT_ARCHIVES_ROOT_STATE_INDEX,
    DDL_TRANSCRIPT_ARCHIVES_CLAUDE_UUID_INDEX,
    DDL_TRANSCRIPT_ARCHIVES_PARENT_INDEX,
    DDL_TRANSCRIPT_RECORDS_UUID_INDEX,
    DDL_TRANSCRIPT_ROOT_DECISIONS_ARCHIVE_INDEX,
)


DDL_V15_TRANSCRIPT_ARCHIVES_SUPERSEDED_BY = (
    "ALTER TABLE transcript_archives ADD COLUMN superseded_by_archive_id "
    "INTEGER REFERENCES transcript_archives(id)"
)

DDL_V15_TRANSCRIPT_ARCHIVES_GROWTH_KIND = (
    "ALTER TABLE transcript_archives ADD COLUMN growth_kind TEXT NOT NULL "
    "DEFAULT 'initial' CHECK (growth_kind IN "
    "('initial', 'append', 'non_append_rewrite'))"
)

DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_ID = (
    "ALTER TABLE transcript_archives ADD COLUMN project_id "
    "INTEGER REFERENCES projects(id)"
)

DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_ROOTED_AT = (
    "ALTER TABLE transcript_archives ADD COLUMN project_rooted_at TEXT"
)

DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_ROOTED_BY = (
    "ALTER TABLE transcript_archives ADD COLUMN project_rooted_by TEXT"
)

DDL_V15_TRANSCRIPT_ROOT_DECISIONS_PROJECT_ID = (
    "ALTER TABLE transcript_root_decisions ADD COLUMN project_id "
    "INTEGER REFERENCES projects(id)"
)

DDL_V15_TRANSCRIPT_ARCHIVES_SUPERSEDED_BY_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_transcript_archives_superseded_by "
    "ON transcript_archives (superseded_by_archive_id)"
)

DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_transcript_archives_project "
    "ON transcript_archives (project_id)"
)

DDL_V15: Tuple[str, ...] = (
    DDL_V15_TRANSCRIPT_ARCHIVES_SUPERSEDED_BY,
    DDL_V15_TRANSCRIPT_ARCHIVES_GROWTH_KIND,
    DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_ID,
    DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_ROOTED_AT,
    DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_ROOTED_BY,
    DDL_V15_TRANSCRIPT_ROOT_DECISIONS_PROJECT_ID,
    DDL_V15_TRANSCRIPT_ARCHIVES_SUPERSEDED_BY_INDEX,
    DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_INDEX,
)


DDL_V22_TRANSCRIPT_ARCHIVES_CONTENT_SHA_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_transcript_archives_content_sha "
    "ON transcript_archives (content_sha256)"
)

DDL_V22_TRANSCRIPT_ARCHIVES_DEDUPE_KIND = (
    "ALTER TABLE transcript_archives ADD COLUMN dedupe_kind TEXT"
)

DEDUPE_KIND_CONTENT_DUPLICATE = "content_duplicate"

DDL_V22: Tuple[str, ...] = (
    DDL_V22_TRANSCRIPT_ARCHIVES_CONTENT_SHA_INDEX,
    DDL_V22_TRANSCRIPT_ARCHIVES_DEDUPE_KIND,
)


DDL_V23_SESSIONS_LAST_WORK_AT = (
    "ALTER TABLE sessions ADD COLUMN last_work_at TEXT"
)

DDL_V23: Tuple[str, ...] = (DDL_V23_SESSIONS_LAST_WORK_AT,)

REVERSAL_SQL_V23: Tuple[str, ...] = ()


DDL_SESSION_GROUP_MEMBERSHIP = """
CREATE TABLE IF NOT EXISTS session_group_membership (
  session_uuid TEXT PRIMARY KEY,
  group_id     INTEGER NOT NULL REFERENCES session_groups(id) ON DELETE CASCADE,
  position     INTEGER NOT NULL DEFAULT 0,
  added_at     TEXT NOT NULL
)
"""

DDL_SESSION_GROUP_MEMBERSHIP_ORDER_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_session_group_membership_order "
    "ON session_group_membership (group_id, position)"
)

DDL_V24: Tuple[str, ...] = (
    DDL_SESSION_GROUP_MEMBERSHIP,
    DDL_SESSION_GROUP_MEMBERSHIP_ORDER_INDEX,
)

REVERSAL_SQL_V24: Tuple[str, ...] = (
    "DROP TABLE IF EXISTS session_group_membership",
)

REVERSAL_DESTROYS[24] = ("session_group_membership (whole table)",)


DDL_V25_SESSIONS_KIND = "ALTER TABLE sessions ADD COLUMN kind TEXT"

DDL_V25_SESSIONS_KIND_BACKFILL = (
    "UPDATE sessions SET kind = 'interactive' "
    "WHERE kind IS NULL AND origin IN ('created', 'adopted')"
)

DDL_V25: Tuple[str, ...] = (
    DDL_V25_SESSIONS_KIND,
    DDL_V25_SESSIONS_KIND_BACKFILL,
)

REVERSAL_SQL_V25: Tuple[str, ...] = ()


DDL_V26_SESSIONS_NOTIFICATIONS_MUTED = (
    "ALTER TABLE sessions ADD COLUMN notifications_muted INTEGER"
)

DDL_V26_SESSIONS_NOTIFICATION_POLICY_GENERATION = (
    "ALTER TABLE sessions ADD COLUMN notification_policy_generation INTEGER"
)

DDL_V26: Tuple[str, ...] = (
    DDL_V26_SESSIONS_NOTIFICATIONS_MUTED,
    DDL_V26_SESSIONS_NOTIFICATION_POLICY_GENERATION,
)

REVERSAL_SQL_V26: Tuple[str, ...] = ()


DDL_INSTALLED_ITEMS = """
CREATE TABLE IF NOT EXISTS installed_items (
  install_id        TEXT PRIMARY KEY,
  item_id           TEXT NOT NULL,
  kind              TEXT NOT NULL,
  publisher         TEXT NOT NULL,
  name              TEXT NOT NULL,
  version           TEXT NOT NULL,
  digest            TEXT NOT NULL,
  scope             TEXT NOT NULL,
  project_path      TEXT NOT NULL DEFAULT '',
  auto_update       INTEGER NOT NULL DEFAULT 0,
  source_index_url  TEXT NOT NULL,
  consented_digest  TEXT,
  consented_body_sha TEXT,
  publisher_key_id  TEXT NOT NULL,
  revision          INTEGER NOT NULL DEFAULT 1,
  installed_at      TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  UNIQUE (item_id, scope, project_path),
  UNIQUE (name, scope, project_path)
)
"""

DDL_INSTALLED_ITEM_TARGETS = """
CREATE TABLE IF NOT EXISTS installed_item_targets (
  install_id TEXT NOT NULL
    REFERENCES installed_items(install_id) ON DELETE CASCADE,
  harness    TEXT NOT NULL,
  path       TEXT NOT NULL,
  PRIMARY KEY (install_id, path)
)
"""

DDL_INSTALLED_LOADOUT_MEMBERS = """
CREATE TABLE IF NOT EXISTS installed_loadout_members (
  install_id        TEXT NOT NULL
    REFERENCES installed_items(install_id) ON DELETE CASCADE,
  item_id           TEXT NOT NULL,
  version           TEXT NOT NULL,
  state             TEXT NOT NULL,
  member_install_id TEXT,
  detail            TEXT,
  PRIMARY KEY (install_id, item_id)
)
"""

DDL_CATALOG_REVOCATIONS_SEEN = """
CREATE TABLE IF NOT EXISTS catalog_revocations_seen (
  index_key_id TEXT NOT NULL,
  kind         TEXT NOT NULL,
  subject      TEXT NOT NULL,
  since        TEXT NOT NULL,
  PRIMARY KEY (index_key_id, kind, subject)
)
"""

DDL_CATALOG_INDEX_STATE = """
CREATE TABLE IF NOT EXISTS catalog_index_state (
  index_key_id        TEXT PRIMARY KEY,
  last_verified_serial INTEGER NOT NULL,
  last_verified_at    TEXT NOT NULL,
  etag                TEXT
)
"""

DDL_V27: Tuple[str, ...] = (
    DDL_INSTALLED_ITEMS,
    DDL_INSTALLED_ITEM_TARGETS,
    DDL_CATALOG_REVOCATIONS_SEEN,
    DDL_CATALOG_INDEX_STATE,
)

REVERSAL_SQL_V27: Tuple[str, ...] = ()


DDL_V28: Tuple[str, ...] = (DDL_INSTALLED_LOADOUT_MEMBERS,)

REVERSAL_SQL_V28: Tuple[str, ...] = ()


REVERSAL_SQL_V29: Tuple[str, ...] = ()


DDL_SESSION_NOTES = """
CREATE TABLE IF NOT EXISTS session_notes (
  session_uuid TEXT PRIMARY KEY REFERENCES sessions(session_uuid),
  body         TEXT NOT NULL,
  revision     INTEGER NOT NULL,
  updated_at   TEXT NOT NULL
)
"""

DDL_V30: Tuple[str, ...] = (DDL_SESSION_NOTES,)

REVERSAL_SQL_V30: Tuple[str, ...] = (
    "DROP TABLE IF EXISTS session_notes",
)

REVERSAL_DESTROYS[30] = ("session_notes (whole table)",)


from src.core.browser_sessions_ddl import REVERSAL_SQL_V32  # noqa: E402

REVERSAL_DESTROYS[32] = ("browser_sessions (whole table)",)


from src.core.session_group_style_ddl import REVERSAL_SQL_V33  # noqa: E402

REVERSAL_DESTROYS[33] = ("session_group_styles (whole table)",)


from src.core.layouts.ddl import REVERSAL_SQL_V34  # noqa: E402

REVERSAL_DESTROYS[34] = (
    "layouts (whole table)",
    "layout_members (whole table)",
)


from src.core.blueprints_ddl import REVERSAL_SQL_V35  # noqa: E402

REVERSAL_DESTROYS[35] = ("blueprints (whole table)",)


from src.core.layouts.style_ddl import REVERSAL_SQL_V36  # noqa: E402

REVERSAL_DESTROYS[36] = ("layout_styles (whole table)",)
from src.core.layouts.broadcast_ddl import REVERSAL_SQL_V37  # noqa: E402

REVERSAL_DESTROYS[37] = ("layout_broadcast_off (whole table)",)
from src.core.item_settings_ddl import REVERSAL_SQL_V38  # noqa: E402

REVERSAL_DESTROYS[38] = ("item_settings (whole table)",)


from src.core.session_group_icon_ddl import REVERSAL_SQL_V39  # noqa: E402

REVERSAL_DESTROYS[39] = ("session_group_styles.icon",)


from src.core.hosts.ddl import REVERSAL_SQL_V40  # noqa: E402

REVERSAL_DESTROYS[40] = ("hosts (whole table)",)


from src.core.skills.consent_via_ddl import REVERSAL_SQL_V41  # noqa: E402

REVERSAL_DESTROYS[41] = ("installed_items.consent_via",)


from src.core.skills.fork_mark_ddl import REVERSAL_SQL_V42  # noqa: E402

REVERSAL_DESTROYS[42] = ("installed_items.forked",)


from src.core.federation.ddl import REVERSAL_SQL_V43  # noqa: E402

REVERSAL_DESTROYS[43] = ("federation_grants (whole table)",)


from src.core.federation.ddl import REVERSAL_SQL_V44  # noqa: E402

REVERSAL_DESTROYS[44] = ("hosts.kind and hosts.peer_* columns",)


from src.core.federation.ddl_peer_sessions import REVERSAL_SQL_V45  # noqa: E402

REVERSAL_DESTROYS[45] = ("peer_sessions (whole table)", "sessions rows with origin peer", "projects rows with a peer:// root")


from src.core.conversation_index.ddl import REVERSAL_SQL_V46  # noqa: E402

REVERSAL_DESTROYS[46] = ("conversation_index (whole table, its FTS5 index and triggers)",)


from src.core.conversation_index.ddl import REVERSAL_SQL_V48  # noqa: E402

REVERSAL_DESTROYS[48] = ("conversation_index.link_basis",)


from src.core.lineage.ddl import REVERSAL_SQL_V49  # noqa: E402

REVERSAL_DESTROYS[49] = ("lineage_edges (whole table)", "lineage_nodes (whole table)", "lineage_sources (whole table)", "conversation_milestones (whole table)",
                         "conversation_index.parent_conversation_id and link_basis (dropped by the step)")


from src.core.app_alerts.ddl import REVERSAL_SQL_V50  # noqa: E402

REVERSAL_DESTROYS[50] = ("app_alerts (whole table: alert history; producers re-raise open conditions)",)


from src.core.db_ddl.pipeline import REVERSAL_SQL_V51  # noqa: E402

REVERSAL_DESTROYS[51] = ("pipeline_jobs (whole table: save backlog and history)", "pipeline_stage_runs (whole table)")


from src.core.db_ddl.search_index import REVERSAL_SQL_V52  # noqa: E402

REVERSAL_DESTROYS[52] = ("session_search_fts, session_search_rows, session_search_docs (whole tables: "
                         "rebuildable from the restore points)",)


from src.core.db_ddl.pipeline import REVERSAL_SQL_V53  # noqa: E402

REVERSAL_DESTROYS[53] = ("pipeline_stage_runs.server", "pipeline_stage_runs.wait_reason")


from src.core.transcript_manifest.ddl import REVERSAL_SQL_V54  # noqa: E402

REVERSAL_DESTROYS[54] = ("transcript_files (whole table: rebuilt by the next scan except the removal history)",)


from src.core.db_ddl.search_index import REVERSAL_SQL_V55  # noqa: E402

REVERSAL_DESTROYS[55] = ("session_search_live (whole table: rebuilt from the live transcripts by the next scans)",
                         "session_search_rows.live_id", "session_search_docs.src_* watermark columns")


from src.core.launch_profiles.ddl import REVERSAL_SQL_V56  # noqa: E402

REVERSAL_DESTROYS[56] = ("sessions.launch_record (the recorded launch of each session)",)

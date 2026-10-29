
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, Sequence

from src.core.work.ladder import cards_rung, data_rungs, feature_rungs, held_rungs, role_rungs, state_rungs, wait_rungs

MIGRATIONS: Sequence[str] = (
    """
    CREATE TABLE meta (k TEXT PRIMARY KEY, v INTEGER NOT NULL) WITHOUT ROWID;
    INSERT INTO meta VALUES ('seq', 0);
    CREATE TABLE items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      list_key TEXT NOT NULL,
      text TEXT NOT NULL,
      note TEXT NOT NULL DEFAULT '',
      position INTEGER NOT NULL,
      created_by TEXT NOT NULL,
      state TEXT NOT NULL,
      claude_done INTEGER NOT NULL DEFAULT 0,
      created_at REAL NOT NULL,
      updated_at REAL NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1,
      created_seq INTEGER NOT NULL,
      seq INTEGER NOT NULL,
      deleted INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX items_list_seq ON items (list_key, seq);
    CREATE TABLE messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      item_id INTEGER NOT NULL REFERENCES items (id),
      author TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      answered INTEGER NOT NULL DEFAULT 0,
      created_at REAL NOT NULL,
      seq INTEGER NOT NULL
    );
    CREATE INDEX messages_item ON messages (item_id, id);
    CREATE INDEX messages_seq ON messages (seq);
    CREATE TABLE reads (
      session_id TEXT NOT NULL, list_key TEXT NOT NULL, cursor INTEGER NOT NULL,
      PRIMARY KEY (session_id, list_key)
    ) WITHOUT ROWID;
    """,
    "ALTER TABLE items ADD COLUMN kind TEXT NOT NULL DEFAULT '';",
    "ALTER TABLE items ADD COLUMN attention_seq INTEGER NOT NULL DEFAULT 0; "
    "ALTER TABLE items ADD COLUMN seen_seq INTEGER NOT NULL DEFAULT 0;",
    feature_rungs.CALLERS_MIGRATION,
    feature_rungs.SENDS_MIGRATION,
    feature_rungs.LIFECYCLE_MIGRATION,
    feature_rungs.GROUPS_MIGRATION,
    feature_rungs.KINDS_MIGRATION,
    feature_rungs.REVIEW_MIGRATION,
    feature_rungs.TITLE_MIGRATION,
    feature_rungs.INFO_READ_MIGRATION,
    feature_rungs.LOOK_READ_MIGRATION,
    feature_rungs.SEND_TARGET_MIGRATION,
    "ALTER TABLE messages ADD COLUMN author_key TEXT NOT NULL DEFAULT ''; "
    "ALTER TABLE items ADD COLUMN created_key TEXT NOT NULL DEFAULT ''; "
    "ALTER TABLE items ADD COLUMN pack_ref TEXT NOT NULL DEFAULT '';",
    feature_rungs.CLAIM_MIGRATION,
    feature_rungs.TRIGGERS_MIGRATION,
    feature_rungs.PARTS_MIGRATION,
    feature_rungs.REPEAT_MIGRATION,
    feature_rungs.SEND_PICK_MIGRATION,
    feature_rungs.REVIEW_ACTION_MIGRATION,
    feature_rungs.FORK_MIGRATION,
    feature_rungs.COLUMN_MIGRATION,
    cards_rung.CARDS_MIGRATION,
    cards_rung.BOARD_MIGRATION,
    feature_rungs.FROM_PROJECT_MIGRATION,
    "ALTER TABLE items RENAME COLUMN pack_ref TO swarm_ref; "
    "UPDATE items SET created_key = 'swarm' WHERE created_key = 'pack'; "
    "UPDATE messages SET author_key = 'swarm' WHERE author_key = 'pack';",
    feature_rungs.NUDGE_MIGRATION,
    feature_rungs.SESSION_PREFS_MIGRATION,
    feature_rungs.INBOX_MIGRATION,
    feature_rungs.GITHUB_ISSUE_MIGRATION,
    feature_rungs.ACTOR_MIGRATION,
    feature_rungs.OWNER_MIGRATION,
    feature_rungs.REVIEW_SUMMARY_MIGRATION,
    state_rungs.DONE_MIGRATION,
    state_rungs.WAITING_MIGRATION,
    state_rungs.TODO_MIGRATION,
    state_rungs.REVIEW_MIGRATION,
    data_rungs.LANE_MIGRATION,
    data_rungs.PERCEIVED_ASK_MIGRATION,
    data_rungs.BLOCKERS_MIGRATION,
    data_rungs.LINEAGE_MIGRATION,
    state_rungs.NUDGE_BASIS_MIGRATION,
    role_rungs.CLAIM_RULE_MIGRATION,
    role_rungs.ROLES_MIGRATION,
    role_rungs.TAG_MIGRATION,
    wait_rungs.WAIT_MIGRATION,
    data_rungs.LINEAGE_FOLD_MIGRATION,
    data_rungs.MESSAGE_RECEIPTS_MIGRATION,
    held_rungs.HELD_MIGRATION,
)

SCHEMA_VERSION = len(MIGRATIONS)

BACKUPS: Mapping[int, str] = MappingProxyType({23: "pre-cards", **state_rungs.BACKUPS, **data_rungs.BACKUPS, **role_rungs.BACKUPS})

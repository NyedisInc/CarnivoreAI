
from __future__ import annotations

SENDS_MIGRATION = (
    "ALTER TABLE items ADD COLUMN joe_seq INTEGER NOT NULL DEFAULT 0; "
    "CREATE TABLE tells (list_key TEXT PRIMARY KEY, cursor INTEGER NOT NULL) WITHOUT ROWID;"
)

SEND_TARGET_MIGRATION = "ALTER TABLE tells ADD COLUMN target TEXT NOT NULL DEFAULT '';"

CALLERS_MIGRATION = (
    "CREATE TABLE callers (session_id TEXT NOT NULL, list_key TEXT NOT NULL, at REAL NOT NULL, "
    "PRIMARY KEY (session_id, list_key)) WITHOUT ROWID;"
)

SEND_PICK_MIGRATION = "CREATE TABLE tell_picks (list_key TEXT PRIMARY KEY, target_key TEXT NOT NULL) WITHOUT ROWID;"

LIFECYCLE_MIGRATION = (
    "ALTER TABLE items ADD COLUMN claude_read_seq INTEGER NOT NULL DEFAULT 0; "
    "ALTER TABLE items ADD COLUMN claude_working INTEGER NOT NULL DEFAULT 0; "
    "UPDATE items SET claude_read_seq = joe_seq WHERE joe_seq <= COALESCE("
    "(SELECT MAX(r.cursor) FROM reads r WHERE r.list_key = items.list_key), 0);"
)

CLAIM_MIGRATION = (
    "ALTER TABLE items ADD COLUMN claude_working_by TEXT NOT NULL DEFAULT ''; "
    "UPDATE items SET claude_working = 0 WHERE claude_working = 1; "
    "CREATE INDEX items_claim ON items(claude_working_by) WHERE claude_working_by != '';"
)

GROUPS_MIGRATION = (
    "CREATE TABLE item_groups ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT, list_key TEXT NOT NULL, name TEXT NOT NULL,"
    " position INTEGER NOT NULL, folded INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL,"
    " created_at REAL NOT NULL, updated_at REAL NOT NULL, seq INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0); "
    "CREATE INDEX item_groups_list ON item_groups (list_key, deleted, position); "
    "ALTER TABLE items ADD COLUMN group_id INTEGER;"
)

KINDS_MIGRATION = (
    "ALTER TABLE items ADD COLUMN info_seq INTEGER NOT NULL DEFAULT 0; "
    "ALTER TABLE items ADD COLUMN call_seq INTEGER NOT NULL DEFAULT 0;"
)

INFO_READ_MIGRATION = (
    "ALTER TABLE messages ADD COLUMN seen INTEGER NOT NULL DEFAULT 0; "
    "UPDATE messages SET seen = 1 WHERE kind = 'info' AND seq <= COALESCE("
    "(SELECT i.seen_seq FROM items i WHERE i.id = messages.item_id), 0);"
)

LOOK_READ_MIGRATION = (
    "UPDATE messages SET seen = 1 WHERE kind = 'attention' AND seq <= COALESCE("
    "(SELECT i.seen_seq FROM items i WHERE i.id = messages.item_id), 0);"
)

PARTS_MIGRATION = "ALTER TABLE messages ADD COLUMN parts TEXT NOT NULL DEFAULT '';"

TRIGGERS_MIGRATION = (
    "CREATE TABLE item_triggers ("
    "item_id INTEGER PRIMARY KEY REFERENCES items (id), "
    "kind TEXT NOT NULL DEFAULT 'at', "
    "fire_at REAL, "
    "fired_at REAL, "
    "last_error TEXT, "
    "updated_at REAL NOT NULL);"
    "CREATE INDEX item_triggers_due ON item_triggers (fire_at) WHERE fired_at IS NULL;"
)

REPEAT_MIGRATION = (
    "ALTER TABLE item_triggers ADD COLUMN repeat_rule TEXT; "
    "ALTER TABLE item_triggers ADD COLUMN paused INTEGER NOT NULL DEFAULT 0; "
    "ALTER TABLE item_triggers ADD COLUMN last_fired_at REAL;"
)

REVIEW_MIGRATION = (
    "ALTER TABLE items ADD COLUMN review_description TEXT; "
    "ALTER TABLE items ADD COLUMN review_link TEXT; "
    "ALTER TABLE items ADD COLUMN review_where TEXT;"
)

REVIEW_ACTION_MIGRATION = "ALTER TABLE items ADD COLUMN review_action TEXT;"

REVIEW_SUMMARY_MIGRATION = "ALTER TABLE items ADD COLUMN review_summary TEXT;"

TITLE_MIGRATION = "ALTER TABLE items ADD COLUMN title TEXT;"

FORK_MIGRATION = "ALTER TABLE items ADD COLUMN forked_from INTEGER;"

COLUMN_MIGRATION = "ALTER TABLE items ADD COLUMN flag_color TEXT; ALTER TABLE items ADD COLUMN flag_reason TEXT;"

FROM_PROJECT_MIGRATION = "ALTER TABLE items ADD COLUMN from_project_id TEXT; ALTER TABLE items ADD COLUMN from_project_name TEXT;"

GITHUB_ISSUE_MIGRATION = "ALTER TABLE items ADD COLUMN github_issue TEXT;"

ACTOR_MIGRATION = (
    "CREATE TABLE write_actors ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, op TEXT NOT NULL, "
    "actor_key TEXT NOT NULL DEFAULT '', actor_session_id TEXT NOT NULL DEFAULT '', "
    "cross_project INTEGER NOT NULL DEFAULT 0, at REAL NOT NULL); "
    "CREATE INDEX write_actors_item ON write_actors (item_id, id); "
    "ALTER TABLE items ADD COLUMN source_item_id INTEGER;"
)

INBOX_MIGRATION = (
    "CREATE TABLE inbox ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "list_key TEXT NOT NULL, "
    "raw_text TEXT NOT NULL, "
    "author TEXT NOT NULL, "
    "created_at REAL NOT NULL, "
    "status TEXT NOT NULL, "
    "delivered_at REAL, "
    "delivered_to TEXT, "
    "filed_at REAL, "
    "item_ids TEXT NOT NULL DEFAULT '[]', "
    "error TEXT);"
    "CREATE INDEX inbox_open ON inbox (status);"
    "ALTER TABLE items ADD COLUMN inbox_id INTEGER;"
    "ALTER TABLE list_prefs ADD COLUMN inbox INTEGER NOT NULL DEFAULT 1;"
)

NUDGE_MIGRATION = (
    "CREATE TABLE list_prefs (list_key TEXT PRIMARY KEY, nudge INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0) WITHOUT ROWID; "
    "CREATE TABLE item_nudges (item_id INTEGER PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0, last_at REAL NOT NULL DEFAULT 0, "
    "basis TEXT NOT NULL DEFAULT '', stalled_at REAL);"
)

SESSION_PREFS_MIGRATION = (
    "CREATE TABLE session_prefs (session_uuid TEXT PRIMARY KEY, nudge INTEGER, updated_at REAL NOT NULL DEFAULT 0) WITHOUT ROWID;"
)

COLUMN = "owner_session_key"

_RUNG_32_TICKED_SQL = "'approved', 'approved_with_note'"


def release_trigger_sql(ticked_sql: str, *, replace: bool = False) -> str:
    drop = "DROP TRIGGER IF EXISTS items_owner_release; " if replace else ""
    return (drop + "CREATE TRIGGER items_owner_release AFTER UPDATE OF state, deleted ON items "
            f"WHEN NEW.{COLUMN} != '' AND (NEW.deleted = 1 OR NEW.state IN ({ticked_sql})) "
            f"BEGIN UPDATE items SET {COLUMN} = '' WHERE id = NEW.id; END; ")


OWNER_MIGRATION = (
    f"ALTER TABLE items ADD COLUMN {COLUMN} TEXT NOT NULL DEFAULT ''; "
    f"UPDATE items SET {COLUMN} = claude_working_by WHERE claude_working = 1 AND claude_working_by != '' AND deleted = 0; "
    "CREATE TRIGGER items_owner_claim AFTER UPDATE OF claude_working_by ON items "
    f"WHEN NEW.claude_working_by != '' AND NEW.claude_working_by != NEW.{COLUMN} "
    f"BEGIN UPDATE items SET {COLUMN} = NEW.claude_working_by WHERE id = NEW.id; END; "
    + release_trigger_sql(_RUNG_32_TICKED_SQL) +
    f"CREATE INDEX items_owner ON items({COLUMN}) WHERE {COLUMN} != '';"
)

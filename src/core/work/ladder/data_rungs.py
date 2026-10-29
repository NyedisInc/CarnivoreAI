
from __future__ import annotations

LANE_MIGRATION = (
    "ALTER TABLE items ADD COLUMN lane TEXT NOT NULL DEFAULT 'task_manager'; "
    "UPDATE items SET lane = 'swarm' WHERE swarm_ref != '' OR created_key = 'swarm' OR list_key LIKE 'agent:%' "
    "OR card_origin LIKE 'agent:%' OR card_origin LIKE 'spawn:%';"
)

PERCEIVED_ASK_MIGRATION = "ALTER TABLE items ADD COLUMN perceived_ask TEXT;"

BLOCKERS_MIGRATION = (
    "CREATE TABLE blockers ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "item_id INTEGER NOT NULL, "
    "kind TEXT NOT NULL, "
    "text TEXT NOT NULL, "
    "evidence TEXT NOT NULL DEFAULT '', "
    "created_by TEXT NOT NULL, "
    "created_at REAL NOT NULL, "
    "cleared_by TEXT, "
    "cleared_at REAL);"
    "CREATE INDEX blockers_item ON blockers (item_id, cleared_at);"
)

LINEAGE_MIGRATION = (
    "CREATE TABLE item_lineage ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "item_id INTEGER NOT NULL, "
    "list_key TEXT NOT NULL, "
    "at REAL NOT NULL, "
    "from_state TEXT NOT NULL, "
    "to_state TEXT NOT NULL, "
    "by TEXT NOT NULL, "
    "detail TEXT NOT NULL DEFAULT '');"
    "CREATE INDEX item_lineage_item ON item_lineage (item_id, at);"
)

LINEAGE_FOLD_MIGRATION = (
    "INSERT INTO card_events (item_id, list_key, at, kind, from_col, to_col, by, detail) "
    "SELECT item_id, list_key, at, 'state', from_state, to_state, by, detail FROM item_lineage ORDER BY id;"
)

MESSAGE_RECEIPTS_MIGRATION = (
    "CREATE TABLE message_receipts ("
    "message_id INTEGER PRIMARY KEY, "
    "item_id INTEGER NOT NULL, "
    "delivered_at REAL, "
    "delivered_to TEXT NOT NULL DEFAULT '', "
    "delivered_label TEXT NOT NULL DEFAULT '', "
    "received_at REAL, "
    "received_by TEXT NOT NULL DEFAULT '', "
    "answered_at REAL) WITHOUT ROWID;"
    "CREATE INDEX message_receipts_item ON message_receipts (item_id);"
)

BACKUPS = {38: "pre-lane", 47: "pre-lineage-fold"}

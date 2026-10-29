
from __future__ import annotations

CLAIM_RULE_MIGRATION = (
    "UPDATE items SET claude_working = 0, claude_working_by = '' WHERE claude_working = 1 AND state != 'open' AND deleted = 0;"
    "CREATE TRIGGER items_claim_leaves_working AFTER UPDATE OF state ON items "
    "WHEN NEW.claude_working = 1 AND NEW.state != 'open' "
    "BEGIN UPDATE items SET claude_working = 0, claude_working_by = '' WHERE id = NEW.id; END;"
)

ROLES_MIGRATION = (
    "CREATE TABLE project_roles (list_key TEXT PRIMARY KEY, lead_key TEXT NOT NULL DEFAULT '', lead_by TEXT NOT NULL DEFAULT '', "
    "lead_at REAL NOT NULL DEFAULT 0, ever_led INTEGER NOT NULL DEFAULT 0) WITHOUT ROWID;"
    "ALTER TABLE session_prefs ADD COLUMN dnd INTEGER NOT NULL DEFAULT 0;"
)

TAG_MIGRATION = (
    "ALTER TABLE items ADD COLUMN tagged_session_key TEXT NOT NULL DEFAULT '';"
    "CREATE INDEX items_tagged ON items(tagged_session_key) WHERE tagged_session_key != '';"
)

BACKUPS = {43: "pre-claim-rule"}


from __future__ import annotations

TABLES = """
CREATE TABLE work_blockers (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL, created_at REAL NOT NULL, cleared_by TEXT, cleared_at REAL);
CREATE TABLE work_callers (session_id TEXT NOT NULL, list_key TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY (session_id, list_key)) WITHOUT ROWID;
CREATE TABLE work_card_deals (
  project_key TEXT PRIMARY KEY,
  state TEXT NOT NULL CHECK (state IN ('waiting', 'delivered', 'answered', 'no_dealer', 'dealing_off', 'gave_up')),
  reasons TEXT NOT NULL DEFAULT '[]',
  offered_ids TEXT NOT NULL DEFAULT '[]',
  requested_at REAL NOT NULL,
  delivered_at REAL,
  answered_at REAL,
  attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE work_card_events (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL,
  list_key TEXT NOT NULL,
  at REAL NOT NULL,
  kind TEXT NOT NULL,
  from_col TEXT NOT NULL DEFAULT '',
  to_col TEXT NOT NULL DEFAULT '',
  by TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE work_card_grants (
  scope TEXT PRIMARY KEY,
  slots INTEGER NOT NULL CHECK (slots BETWEEN 0 AND 20),
  set_by TEXT NOT NULL,
  set_at REAL NOT NULL,
  reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE work_card_rules (
  list_key TEXT PRIMARY KEY,
  dealing INTEGER,
  auto_done INTEGER NOT NULL DEFAULT 0,
  auto_validate INTEGER NOT NULL DEFAULT 0,
  reorder TEXT NOT NULL DEFAULT 'suggest' CHECK (reorder IN ('suggest', 'auto')),
  pace TEXT NOT NULL DEFAULT 'normal' CHECK (pace IN ('normal', 'asap')),
  updated_at REAL,
  updated_by TEXT NOT NULL DEFAULT ''
);
CREATE TABLE work_card_suggestions (
  id INTEGER PRIMARY KEY,
  list_key TEXT NOT NULL,
  card_id INTEGER NOT NULL,
  before_id INTEGER,
  by_agent INTEGER NOT NULL,
  reason TEXT NOT NULL,
  at REAL NOT NULL,
  state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'applied', 'dismissed'))
);
CREATE TABLE work_held_tells (list_key TEXT PRIMARY KEY, target TEXT NOT NULL, label TEXT, code TEXT, reason TEXT NOT NULL DEFAULT '', since REAL NOT NULL, deadline REAL NOT NULL, params TEXT NOT NULL DEFAULT '{}') WITHOUT ROWID;
CREATE TABLE work_inbox (id INTEGER PRIMARY KEY AUTOINCREMENT, list_key TEXT NOT NULL, raw_text TEXT NOT NULL, author TEXT NOT NULL, created_at REAL NOT NULL, status TEXT NOT NULL, delivered_at REAL, delivered_to TEXT, filed_at REAL, item_ids TEXT NOT NULL DEFAULT '[]', error TEXT);
CREATE TABLE work_item_groups ( id INTEGER PRIMARY KEY AUTOINCREMENT, list_key TEXT NOT NULL, name TEXT NOT NULL, position INTEGER NOT NULL, folded INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, seq INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE work_item_lineage (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, list_key TEXT NOT NULL, at REAL NOT NULL, from_state TEXT NOT NULL, to_state TEXT NOT NULL, by TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
CREATE TABLE work_item_nudges (item_id INTEGER PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0, last_at REAL NOT NULL DEFAULT 0, basis TEXT NOT NULL DEFAULT '', stalled_at REAL);
CREATE TABLE work_item_triggers (item_id INTEGER PRIMARY KEY REFERENCES work_items (id), kind TEXT NOT NULL DEFAULT 'at', fire_at REAL, fired_at REAL, last_error TEXT, updated_at REAL NOT NULL, repeat_rule TEXT, paused INTEGER NOT NULL DEFAULT 0, last_fired_at REAL);
CREATE TABLE work_item_waits (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, waiting_on TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'other', set_by TEXT NOT NULL DEFAULT '', set_at REAL NOT NULL, expect_by REAL NOT NULL, deadline REAL NOT NULL, extended INTEGER NOT NULL DEFAULT 0, extend_reason TEXT NOT NULL DEFAULT '', check_kind TEXT NOT NULL DEFAULT '', check_json TEXT NOT NULL DEFAULT '', check_runs INTEGER NOT NULL DEFAULT 0, check_last_at REAL, check_next_at REAL, check_result TEXT NOT NULL DEFAULT '', token_hash TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active', legacy INTEGER NOT NULL DEFAULT 0, ended_at REAL, ended_note TEXT NOT NULL DEFAULT '');
CREATE TABLE work_items (
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
    , kind TEXT NOT NULL DEFAULT '', attention_seq INTEGER NOT NULL DEFAULT 0, seen_seq INTEGER NOT NULL DEFAULT 0, joe_seq INTEGER NOT NULL DEFAULT 0, claude_read_seq INTEGER NOT NULL DEFAULT 0, claude_working INTEGER NOT NULL DEFAULT 0, group_id INTEGER, info_seq INTEGER NOT NULL DEFAULT 0, call_seq INTEGER NOT NULL DEFAULT 0, review_description TEXT, review_link TEXT, review_where TEXT, title TEXT, created_key TEXT NOT NULL DEFAULT '', swarm_ref TEXT NOT NULL DEFAULT '', claude_working_by TEXT NOT NULL DEFAULT '', review_action TEXT, forked_from INTEGER, flag_color TEXT, flag_reason TEXT, card_holder INTEGER, card_last_holder INTEGER, card_held_since REAL, card_started_at REAL, card_beat_at REAL, card_refresh_asked_at REAL, card_parent INTEGER, card_origin TEXT NOT NULL DEFAULT '', card_dealt_to INTEGER, card_paused_mode TEXT NOT NULL DEFAULT '' CHECK (card_paused_mode IN ('', 'after_step', 'now')), card_paused_by INTEGER, card_paused_at REAL, card_mark TEXT NOT NULL DEFAULT '' CHECK (card_mark IN ('', 'handing_off', 'stalled', 'waiting_for_slot', 'validating', 'validated', 'validation_failed')), card_mark_at REAL, card_accepted_at REAL, card_report_id INTEGER, card_pin_agent INTEGER, card_pin_place INTEGER NOT NULL DEFAULT 0, card_progress INTEGER, card_result TEXT NOT NULL DEFAULT '', card_handoff TEXT NOT NULL DEFAULT '', card_proof TEXT NOT NULL DEFAULT '', card_validation TEXT NOT NULL DEFAULT '', phone_sent_at REAL, card_summary TEXT NOT NULL DEFAULT '', card_queued INTEGER NOT NULL DEFAULT 0, card_archived_at REAL, card_auto_promote INTEGER NOT NULL DEFAULT 0, card_owner_note TEXT NOT NULL DEFAULT '', from_project_id TEXT, from_project_name TEXT, inbox_id INTEGER, github_issue TEXT, source_item_id INTEGER, owner_session_key TEXT NOT NULL DEFAULT '', review_summary TEXT, lane TEXT NOT NULL DEFAULT 'task_manager', perceived_ask TEXT, tagged_session_key TEXT NOT NULL DEFAULT '');
CREATE TABLE work_list_prefs (list_key TEXT PRIMARY KEY, nudge INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0, inbox INTEGER NOT NULL DEFAULT 1) WITHOUT ROWID;
CREATE TABLE work_message_receipts (message_id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, delivered_at REAL, delivered_to TEXT NOT NULL DEFAULT '', delivered_label TEXT NOT NULL DEFAULT '', received_at REAL, received_by TEXT NOT NULL DEFAULT '', answered_at REAL) WITHOUT ROWID;
CREATE TABLE work_messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      item_id INTEGER NOT NULL REFERENCES work_items (id),
      author TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      answered INTEGER NOT NULL DEFAULT 0,
      created_at REAL NOT NULL,
      seq INTEGER NOT NULL
    , seen INTEGER NOT NULL DEFAULT 0, author_key TEXT NOT NULL DEFAULT '', parts TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '');
CREATE TABLE work_meta (k TEXT PRIMARY KEY, v INTEGER NOT NULL) WITHOUT ROWID;
CREATE TABLE work_project_roles (list_key TEXT PRIMARY KEY, lead_key TEXT NOT NULL DEFAULT '', lead_by TEXT NOT NULL DEFAULT '', lead_at REAL NOT NULL DEFAULT 0, ever_led INTEGER NOT NULL DEFAULT 0) WITHOUT ROWID;
CREATE TABLE work_reads (
      session_id TEXT NOT NULL, list_key TEXT NOT NULL, cursor INTEGER NOT NULL,
      PRIMARY KEY (session_id, list_key)
    ) WITHOUT ROWID;
CREATE TABLE work_session_prefs (session_uuid TEXT PRIMARY KEY, nudge INTEGER, updated_at REAL NOT NULL DEFAULT 0, dnd INTEGER NOT NULL DEFAULT 0) WITHOUT ROWID;
CREATE TABLE work_send_picks (list_key TEXT PRIMARY KEY, target_key TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE work_sends (list_key TEXT PRIMARY KEY, cursor INTEGER NOT NULL, target TEXT NOT NULL DEFAULT '') WITHOUT ROWID;
CREATE TABLE work_write_actors (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, op TEXT NOT NULL, actor_key TEXT NOT NULL DEFAULT '', actor_session_id TEXT NOT NULL DEFAULT '', cross_project INTEGER NOT NULL DEFAULT 0, at REAL NOT NULL);
CREATE INDEX work_blockers_item ON work_blockers (item_id, cleared_at);
CREATE INDEX work_card_events_item ON work_card_events (item_id, at);
CREATE INDEX work_card_events_kind ON work_card_events (kind, at);
CREATE INDEX work_inbox_open ON work_inbox (status);
CREATE INDEX work_item_groups_list ON work_item_groups (list_key, deleted, position);
CREATE INDEX work_item_lineage_item ON work_item_lineage (item_id, at);
CREATE INDEX work_item_triggers_due ON work_item_triggers (fire_at) WHERE fired_at IS NULL;
CREATE INDEX work_item_waits_item ON work_item_waits (item_id, status);
CREATE INDEX work_item_waits_live ON work_item_waits (status, deadline) WHERE status IN ('active', 'escalated');
CREATE INDEX work_items_card_holder ON work_items (card_holder) WHERE card_holder IS NOT NULL;
CREATE INDEX work_items_card_parent ON work_items (card_parent) WHERE card_parent IS NOT NULL;
CREATE INDEX work_items_card_report ON work_items (card_report_id) WHERE card_report_id IS NOT NULL;
CREATE INDEX work_items_claim ON work_items(claude_working_by) WHERE claude_working_by != '';
CREATE INDEX work_items_list_seq ON work_items (list_key, seq);
CREATE INDEX work_items_owner ON work_items(owner_session_key) WHERE owner_session_key != '';
CREATE INDEX work_items_tagged ON work_items(tagged_session_key) WHERE tagged_session_key != '';
CREATE INDEX work_message_receipts_item ON work_message_receipts (item_id);
CREATE INDEX work_messages_item ON work_messages (item_id, id);
CREATE INDEX work_messages_seq ON work_messages (seq);
CREATE INDEX work_write_actors_item ON work_write_actors (item_id, id);
"""

TRIGGERS = """
CREATE TRIGGER work_items_claim_leaves_working AFTER UPDATE OF state ON work_items WHEN NEW.claude_working = 1 AND NEW.state != 'open' BEGIN UPDATE work_items SET claude_working = 0, claude_working_by = '' WHERE id = NEW.id; END;
CREATE TRIGGER work_items_owner_claim AFTER UPDATE OF claude_working_by ON work_items WHEN NEW.claude_working_by != '' AND NEW.claude_working_by != NEW.owner_session_key BEGIN UPDATE work_items SET owner_session_key = NEW.claude_working_by WHERE id = NEW.id; END;
CREATE TRIGGER work_items_owner_release AFTER UPDATE OF state, deleted ON work_items WHEN NEW.owner_session_key != '' AND (NEW.deleted = 1 OR NEW.state IN ('done')) BEGIN UPDATE work_items SET owner_session_key = '' WHERE id = NEW.id; END;
CREATE TRIGGER work_items_wait_ends AFTER UPDATE OF state ON work_items WHEN OLD.state = 'waiting' AND NEW.state != 'waiting' BEGIN UPDATE work_item_waits SET status = CASE WHEN NEW.state IN ('review', 'done') THEN 'settled' ELSE 'ended' END, token_hash = '', ended_at = CAST(strftime('%s', 'now') AS REAL) WHERE item_id = NEW.id AND status IN ('active', 'escalated'); END;
CREATE TRIGGER work_items_wait_ends_on_delete AFTER UPDATE OF deleted ON work_items WHEN NEW.deleted = 1 BEGIN UPDATE work_item_waits SET status = 'ended', token_hash = '', ended_at = CAST(strftime('%s', 'now') AS REAL) WHERE item_id = NEW.id AND status IN ('active', 'escalated'); END;
"""

IMPORTS = """
CREATE TABLE work_imports (id INTEGER PRIMARY KEY CHECK (id = 1), store_home TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('import', 'fresh')), source TEXT NOT NULL DEFAULT '', source_version INTEGER, source_sha256 TEXT NOT NULL DEFAULT '', counts TEXT NOT NULL DEFAULT '{}', digests TEXT NOT NULL DEFAULT '{}', imported_at TEXT NOT NULL);
"""

W1 = TABLES + TRIGGERS + IMPORTS

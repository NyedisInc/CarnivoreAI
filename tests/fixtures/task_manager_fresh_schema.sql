-- user_version 49
-- index blockers_item on blockers
CREATE INDEX blockers_item ON blockers (item_id, cleared_at);
-- index card_events_item on card_events
CREATE INDEX card_events_item ON card_events (item_id, at);
-- index card_events_kind on card_events
CREATE INDEX card_events_kind ON card_events (kind, at);
-- index inbox_open on inbox
CREATE INDEX inbox_open ON inbox (status);
-- index item_groups_list on item_groups
CREATE INDEX item_groups_list ON item_groups (list_key, deleted, position);
-- index item_lineage_item on item_lineage
CREATE INDEX item_lineage_item ON item_lineage (item_id, at);
-- index item_triggers_due on item_triggers
CREATE INDEX item_triggers_due ON item_triggers (fire_at) WHERE fired_at IS NULL;
-- index item_waits_item on item_waits
CREATE INDEX item_waits_item ON item_waits (item_id, status);
-- index item_waits_live on item_waits
CREATE INDEX item_waits_live ON item_waits (status, deadline) WHERE status IN ('active', 'escalated');
-- index items_card_holder on items
CREATE INDEX items_card_holder ON items (card_holder) WHERE card_holder IS NOT NULL;
-- index items_card_parent on items
CREATE INDEX items_card_parent ON items (card_parent) WHERE card_parent IS NOT NULL;
-- index items_card_report on items
CREATE INDEX items_card_report ON items (card_report_id) WHERE card_report_id IS NOT NULL;
-- index items_claim on items
CREATE INDEX items_claim ON items(claude_working_by) WHERE claude_working_by != '';
-- index items_list_seq on items
CREATE INDEX items_list_seq ON items (list_key, seq);
-- index items_owner on items
CREATE INDEX items_owner ON items(owner_session_key) WHERE owner_session_key != '';
-- index items_tagged on items
CREATE INDEX items_tagged ON items(tagged_session_key) WHERE tagged_session_key != '';
-- index message_receipts_item on message_receipts
CREATE INDEX message_receipts_item ON message_receipts (item_id);
-- index messages_item on messages
CREATE INDEX messages_item ON messages (item_id, id);
-- index messages_seq on messages
CREATE INDEX messages_seq ON messages (seq);
-- index write_actors_item on write_actors
CREATE INDEX write_actors_item ON write_actors (item_id, id);
-- table blockers on blockers
CREATE TABLE blockers (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL, created_at REAL NOT NULL, cleared_by TEXT, cleared_at REAL);
-- table callers on callers
CREATE TABLE callers (session_id TEXT NOT NULL, list_key TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY (session_id, list_key)) WITHOUT ROWID;
-- table card_deals on card_deals
CREATE TABLE card_deals (
  project_key TEXT PRIMARY KEY,
  state TEXT NOT NULL CHECK (state IN ('waiting', 'delivered', 'answered', 'no_dealer', 'dealing_off', 'gave_up')),
  reasons TEXT NOT NULL DEFAULT '[]',
  offered_ids TEXT NOT NULL DEFAULT '[]',
  requested_at REAL NOT NULL,
  delivered_at REAL,
  answered_at REAL,
  attempts INTEGER NOT NULL DEFAULT 0
);
-- table card_events on card_events
CREATE TABLE card_events (
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
-- table card_grants on card_grants
CREATE TABLE card_grants (
  scope TEXT PRIMARY KEY,
  slots INTEGER NOT NULL CHECK (slots BETWEEN 0 AND 20),
  set_by TEXT NOT NULL,
  set_at REAL NOT NULL,
  reason TEXT NOT NULL DEFAULT ''
);
-- table card_rules on card_rules
CREATE TABLE card_rules (
  list_key TEXT PRIMARY KEY,
  dealing INTEGER,
  auto_done INTEGER NOT NULL DEFAULT 0,
  auto_validate INTEGER NOT NULL DEFAULT 0,
  reorder TEXT NOT NULL DEFAULT 'suggest' CHECK (reorder IN ('suggest', 'auto')),
  pace TEXT NOT NULL DEFAULT 'normal' CHECK (pace IN ('normal', 'asap')),
  updated_at REAL,
  updated_by TEXT NOT NULL DEFAULT ''
);
-- table card_suggestions on card_suggestions
CREATE TABLE card_suggestions (
  id INTEGER PRIMARY KEY,
  list_key TEXT NOT NULL,
  card_id INTEGER NOT NULL,
  before_id INTEGER,
  by_agent INTEGER NOT NULL,
  reason TEXT NOT NULL,
  at REAL NOT NULL,
  state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'applied', 'dismissed'))
);
-- table held_tells on held_tells
CREATE TABLE held_tells (list_key TEXT PRIMARY KEY, target TEXT NOT NULL, label TEXT, code TEXT, reason TEXT NOT NULL DEFAULT '', since REAL NOT NULL, deadline REAL NOT NULL, params TEXT NOT NULL DEFAULT '{}') WITHOUT ROWID;
-- table inbox on inbox
CREATE TABLE inbox (id INTEGER PRIMARY KEY AUTOINCREMENT, list_key TEXT NOT NULL, raw_text TEXT NOT NULL, author TEXT NOT NULL, created_at REAL NOT NULL, status TEXT NOT NULL, delivered_at REAL, delivered_to TEXT, filed_at REAL, item_ids TEXT NOT NULL DEFAULT '[]', error TEXT);
-- table item_groups on item_groups
CREATE TABLE item_groups ( id INTEGER PRIMARY KEY AUTOINCREMENT, list_key TEXT NOT NULL, name TEXT NOT NULL, position INTEGER NOT NULL, folded INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, seq INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
-- table item_lineage on item_lineage
CREATE TABLE item_lineage (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, list_key TEXT NOT NULL, at REAL NOT NULL, from_state TEXT NOT NULL, to_state TEXT NOT NULL, by TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
-- table item_nudges on item_nudges
CREATE TABLE item_nudges (item_id INTEGER PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0, last_at REAL NOT NULL DEFAULT 0, basis TEXT NOT NULL DEFAULT '', stalled_at REAL);
-- table item_triggers on item_triggers
CREATE TABLE item_triggers (item_id INTEGER PRIMARY KEY REFERENCES items (id), kind TEXT NOT NULL DEFAULT 'at', fire_at REAL, fired_at REAL, last_error TEXT, updated_at REAL NOT NULL, repeat_rule TEXT, paused INTEGER NOT NULL DEFAULT 0, last_fired_at REAL);
-- table item_waits on item_waits
CREATE TABLE item_waits (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, waiting_on TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'other', set_by TEXT NOT NULL DEFAULT '', set_at REAL NOT NULL, expect_by REAL NOT NULL, deadline REAL NOT NULL, extended INTEGER NOT NULL DEFAULT 0, extend_reason TEXT NOT NULL DEFAULT '', check_kind TEXT NOT NULL DEFAULT '', check_json TEXT NOT NULL DEFAULT '', check_runs INTEGER NOT NULL DEFAULT 0, check_last_at REAL, check_next_at REAL, check_result TEXT NOT NULL DEFAULT '', token_hash TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active', legacy INTEGER NOT NULL DEFAULT 0, ended_at REAL, ended_note TEXT NOT NULL DEFAULT '');
-- table items on items
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
    , kind TEXT NOT NULL DEFAULT '', attention_seq INTEGER NOT NULL DEFAULT 0, seen_seq INTEGER NOT NULL DEFAULT 0, joe_seq INTEGER NOT NULL DEFAULT 0, claude_read_seq INTEGER NOT NULL DEFAULT 0, claude_working INTEGER NOT NULL DEFAULT 0, group_id INTEGER, info_seq INTEGER NOT NULL DEFAULT 0, call_seq INTEGER NOT NULL DEFAULT 0, review_description TEXT, review_link TEXT, review_where TEXT, title TEXT, created_key TEXT NOT NULL DEFAULT '', swarm_ref TEXT NOT NULL DEFAULT '', claude_working_by TEXT NOT NULL DEFAULT '', review_action TEXT, forked_from INTEGER, flag_color TEXT, flag_reason TEXT, card_holder INTEGER, card_last_holder INTEGER, card_held_since REAL, card_started_at REAL, card_beat_at REAL, card_refresh_asked_at REAL, card_parent INTEGER, card_origin TEXT NOT NULL DEFAULT '', card_dealt_to INTEGER, card_paused_mode TEXT NOT NULL DEFAULT '' CHECK (card_paused_mode IN ('', 'after_step', 'now')), card_paused_by INTEGER, card_paused_at REAL, card_mark TEXT NOT NULL DEFAULT '' CHECK (card_mark IN ('', 'handing_off', 'stalled', 'waiting_for_slot', 'validating', 'validated', 'validation_failed')), card_mark_at REAL, card_accepted_at REAL, card_report_id INTEGER, card_pin_agent INTEGER, card_pin_place INTEGER NOT NULL DEFAULT 0, card_progress INTEGER, card_result TEXT NOT NULL DEFAULT '', card_handoff TEXT NOT NULL DEFAULT '', card_proof TEXT NOT NULL DEFAULT '', card_validation TEXT NOT NULL DEFAULT '', phone_sent_at REAL, card_summary TEXT NOT NULL DEFAULT '', card_queued INTEGER NOT NULL DEFAULT 0, card_archived_at REAL, card_auto_promote INTEGER NOT NULL DEFAULT 0, card_owner_note TEXT NOT NULL DEFAULT '', from_project_id TEXT, from_project_name TEXT, inbox_id INTEGER, github_issue TEXT, source_item_id INTEGER, owner_session_key TEXT NOT NULL DEFAULT '', review_summary TEXT, lane TEXT NOT NULL DEFAULT 'task_manager', perceived_ask TEXT, tagged_session_key TEXT NOT NULL DEFAULT '');
-- table list_prefs on list_prefs
CREATE TABLE list_prefs (list_key TEXT PRIMARY KEY, nudge INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0, inbox INTEGER NOT NULL DEFAULT 1) WITHOUT ROWID;
-- table message_receipts on message_receipts
CREATE TABLE message_receipts (message_id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, delivered_at REAL, delivered_to TEXT NOT NULL DEFAULT '', delivered_label TEXT NOT NULL DEFAULT '', received_at REAL, received_by TEXT NOT NULL DEFAULT '', answered_at REAL) WITHOUT ROWID;
-- table messages on messages
CREATE TABLE messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      item_id INTEGER NOT NULL REFERENCES items (id),
      author TEXT NOT NULL,
      kind TEXT NOT NULL,
      text TEXT NOT NULL,
      answered INTEGER NOT NULL DEFAULT 0,
      created_at REAL NOT NULL,
      seq INTEGER NOT NULL
    , seen INTEGER NOT NULL DEFAULT 0, author_key TEXT NOT NULL DEFAULT '', parts TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '');
-- table meta on meta
CREATE TABLE meta (k TEXT PRIMARY KEY, v INTEGER NOT NULL) WITHOUT ROWID;
-- table project_roles on project_roles
CREATE TABLE project_roles (list_key TEXT PRIMARY KEY, lead_key TEXT NOT NULL DEFAULT '', lead_by TEXT NOT NULL DEFAULT '', lead_at REAL NOT NULL DEFAULT 0, ever_led INTEGER NOT NULL DEFAULT 0) WITHOUT ROWID;
-- table reads on reads
CREATE TABLE reads (
      session_id TEXT NOT NULL, list_key TEXT NOT NULL, cursor INTEGER NOT NULL,
      PRIMARY KEY (session_id, list_key)
    ) WITHOUT ROWID;
-- table session_prefs on session_prefs
CREATE TABLE session_prefs (session_uuid TEXT PRIMARY KEY, nudge INTEGER, updated_at REAL NOT NULL DEFAULT 0, dnd INTEGER NOT NULL DEFAULT 0) WITHOUT ROWID;
-- table tell_picks on tell_picks
CREATE TABLE tell_picks (list_key TEXT PRIMARY KEY, target_key TEXT NOT NULL) WITHOUT ROWID;
-- table tells on tells
CREATE TABLE tells (list_key TEXT PRIMARY KEY, cursor INTEGER NOT NULL, target TEXT NOT NULL DEFAULT '') WITHOUT ROWID;
-- table write_actors on write_actors
CREATE TABLE write_actors (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, op TEXT NOT NULL, actor_key TEXT NOT NULL DEFAULT '', actor_session_id TEXT NOT NULL DEFAULT '', cross_project INTEGER NOT NULL DEFAULT 0, at REAL NOT NULL);
-- trigger items_claim_leaves_working on items
CREATE TRIGGER items_claim_leaves_working AFTER UPDATE OF state ON items WHEN NEW.claude_working = 1 AND NEW.state != 'open' BEGIN UPDATE items SET claude_working = 0, claude_working_by = '' WHERE id = NEW.id; END;
-- trigger items_owner_claim on items
CREATE TRIGGER items_owner_claim AFTER UPDATE OF claude_working_by ON items WHEN NEW.claude_working_by != '' AND NEW.claude_working_by != NEW.owner_session_key BEGIN UPDATE items SET owner_session_key = NEW.claude_working_by WHERE id = NEW.id; END;
-- trigger items_owner_release on items
CREATE TRIGGER items_owner_release AFTER UPDATE OF state, deleted ON items WHEN NEW.owner_session_key != '' AND (NEW.deleted = 1 OR NEW.state IN ('done')) BEGIN UPDATE items SET owner_session_key = '' WHERE id = NEW.id; END;
-- trigger items_wait_ends on items
CREATE TRIGGER items_wait_ends AFTER UPDATE OF state ON items WHEN OLD.state = 'waiting' AND NEW.state != 'waiting' BEGIN UPDATE item_waits SET status = CASE WHEN NEW.state IN ('review', 'done') THEN 'settled' ELSE 'ended' END, token_hash = '', ended_at = CAST(strftime('%s', 'now') AS REAL) WHERE item_id = NEW.id AND status IN ('active', 'escalated'); END;
-- trigger items_wait_ends_on_delete on items
CREATE TRIGGER items_wait_ends_on_delete AFTER UPDATE OF deleted ON items WHEN NEW.deleted = 1 BEGIN UPDATE item_waits SET status = 'ended', token_hash = '', ended_at = CAST(strftime('%s', 'now') AS REAL) WHERE item_id = NEW.id AND status IN ('active', 'escalated'); END;

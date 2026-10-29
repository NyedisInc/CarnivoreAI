
from __future__ import annotations

CARDS_MIGRATION = """
ALTER TABLE items ADD COLUMN card_holder INTEGER;
ALTER TABLE items ADD COLUMN card_last_holder INTEGER;
ALTER TABLE items ADD COLUMN card_held_since REAL;
ALTER TABLE items ADD COLUMN card_started_at REAL;
ALTER TABLE items ADD COLUMN card_beat_at REAL;
ALTER TABLE items ADD COLUMN card_refresh_asked_at REAL;
ALTER TABLE items ADD COLUMN card_parent INTEGER;
ALTER TABLE items ADD COLUMN card_origin TEXT NOT NULL DEFAULT '';
ALTER TABLE items ADD COLUMN card_dealt_to INTEGER;
ALTER TABLE items ADD COLUMN card_paused_mode TEXT NOT NULL DEFAULT '' CHECK (card_paused_mode IN ('', 'after_step', 'now'));
ALTER TABLE items ADD COLUMN card_paused_by INTEGER;
ALTER TABLE items ADD COLUMN card_paused_at REAL;
ALTER TABLE items ADD COLUMN card_mark TEXT NOT NULL DEFAULT '' CHECK (card_mark IN ('', 'handing_off', 'stalled', 'waiting_for_slot', 'validating', 'validated', 'validation_failed'));
ALTER TABLE items ADD COLUMN card_mark_at REAL;
ALTER TABLE items ADD COLUMN card_accepted_at REAL;
ALTER TABLE items ADD COLUMN card_report_id INTEGER;
ALTER TABLE items ADD COLUMN card_pin_agent INTEGER;
ALTER TABLE items ADD COLUMN card_pin_place INTEGER NOT NULL DEFAULT 0;
ALTER TABLE items ADD COLUMN card_progress INTEGER;
ALTER TABLE items ADD COLUMN card_result TEXT NOT NULL DEFAULT '';
ALTER TABLE items ADD COLUMN card_handoff TEXT NOT NULL DEFAULT '';
ALTER TABLE items ADD COLUMN card_proof TEXT NOT NULL DEFAULT '';
ALTER TABLE items ADD COLUMN card_validation TEXT NOT NULL DEFAULT '';
ALTER TABLE items ADD COLUMN phone_sent_at REAL;
ALTER TABLE messages ADD COLUMN category TEXT NOT NULL DEFAULT '';
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
CREATE INDEX card_events_item ON card_events (item_id, at);
CREATE INDEX card_events_kind ON card_events (kind, at);
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
CREATE TABLE card_grants (
  scope TEXT PRIMARY KEY,
  slots INTEGER NOT NULL CHECK (slots BETWEEN 0 AND 20),
  set_by TEXT NOT NULL,
  set_at REAL NOT NULL,
  reason TEXT NOT NULL DEFAULT ''
);
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
CREATE INDEX items_card_holder ON items (card_holder) WHERE card_holder IS NOT NULL;
CREATE INDEX items_card_parent ON items (card_parent) WHERE card_parent IS NOT NULL;
CREATE INDEX items_card_report ON items (card_report_id) WHERE card_report_id IS NOT NULL;
"""


BOARD_MIGRATION = """
ALTER TABLE items ADD COLUMN card_summary TEXT NOT NULL DEFAULT '';
ALTER TABLE items ADD COLUMN card_queued INTEGER NOT NULL DEFAULT 0;
ALTER TABLE items ADD COLUMN card_archived_at REAL;
ALTER TABLE items ADD COLUMN card_auto_promote INTEGER NOT NULL DEFAULT 0;
ALTER TABLE items ADD COLUMN card_owner_note TEXT NOT NULL DEFAULT '';
"""

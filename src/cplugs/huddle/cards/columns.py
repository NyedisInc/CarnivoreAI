
from __future__ import annotations

CARD_COLS = (
    "card_holder, card_last_holder, card_held_since, card_started_at, card_beat_at, card_refresh_asked_at, card_parent, "
    "card_origin, card_dealt_to, card_paused_mode, card_paused_by, card_paused_at, card_mark, card_mark_at, "
    "card_accepted_at, card_report_id, card_pin_agent, card_pin_place, card_progress, card_result, card_handoff, "
    "card_proof, card_validation, claude_working_by, phone_sent_at, card_summary, card_queued, card_archived_at, card_auto_promote, card_owner_note"
)

CHAT_KINDS = ("question", "info")

COLUMNS = ("todo", "in_progress", "review", "done")

MARKS = ("handing_off", "stalled", "waiting_for_slot", "validating", "validated", "validation_failed")

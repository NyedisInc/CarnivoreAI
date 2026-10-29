
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, Tuple

PREFIX = "work_"

ITEMS = "work_items"
MESSAGES = "work_messages"
META = "work_meta"
READS = "work_reads"
CALLERS = "work_callers"
TELLS = "work_sends"
TELL_PICKS = "work_send_picks"
ITEM_GROUPS = "work_item_groups"
ITEM_TRIGGERS = "work_item_triggers"
ITEM_NUDGES = "work_item_nudges"
LIST_PREFS = "work_list_prefs"
SESSION_PREFS = "work_session_prefs"
INBOX = "work_inbox"
WRITE_ACTORS = "work_write_actors"
BLOCKERS = "work_blockers"
ITEM_LINEAGE = "work_item_lineage"
ITEM_WAITS = "work_item_waits"
MESSAGE_RECEIPTS = "work_message_receipts"
PROJECT_ROLES = "work_project_roles"
CARD_EVENTS = "work_card_events"
CARD_RULES = "work_card_rules"
CARD_GRANTS = "work_card_grants"
CARD_DEALS = "work_card_deals"
CARD_SUGGESTIONS = "work_card_suggestions"
HELD_SENDS = "work_held_sends"
IMPORTS = "work_imports"

ALL: Tuple[str, ...] = (
    ITEMS, MESSAGES, META, READS, CALLERS, TELLS, TELL_PICKS, ITEM_GROUPS, ITEM_TRIGGERS, ITEM_NUDGES, LIST_PREFS, SESSION_PREFS,
    INBOX, WRITE_ACTORS, BLOCKERS, ITEM_LINEAGE, ITEM_WAITS, MESSAGE_RECEIPTS, PROJECT_ROLES, CARD_EVENTS, CARD_RULES, CARD_GRANTS,
    CARD_DEALS, CARD_SUGGESTIONS, HELD_SENDS,
)

STORED: Tuple[str, ...] = ALL + (IMPORTS,)

_RENAMED = {TELLS: "tells", TELL_PICKS: "tell_picks", META: "meta", HELD_SENDS: "held_tells"}
LEGACY_NAMES: Mapping[str, str] = MappingProxyType({name: _RENAMED.get(name, name[len(PREFIX):]) for name in ALL})

AT_W1: Mapping[str, str] = MappingProxyType({HELD_SENDS: "work_held_tells"})


def at_w1(name: str) -> str:
    return AT_W1.get(name, name)


from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

SELF = "self"
NATURAL = "natural"
REF = "ref"
KEEP_OPAQUE = "opaque"
NULL_FOREIGN = "null_foreign"
LIST_KEY = "list_key"
STATS_KEY = "stats_key"
KINDS = (SELF, NATURAL, REF, KEEP_OPAQUE, NULL_FOREIGN, LIST_KEY, STATS_KEY)


@dataclass(frozen=True)
class KeyRule:

    kind: str
    target: Optional[str] = None


def _parse(code: str) -> KeyRule:
    if code.startswith("ref:"):
        return KeyRule(REF, code[4:])
    return KeyRule({"self": SELF, "nat": NATURAL, "opaque": KEEP_OPAQUE, "null": NULL_FOREIGN, "list": LIST_KEY,
                    "stats": STATS_KEY}[code])


_SESSION = "ref:sessions.session_uuid"
_SESSION_ID = "ref:sessions.id"
_ITEM = "ref:work_items.id"
_PROJECT = "ref:projects.id"

_CODES: Dict[str, Dict[str, str]] = {
    "cloude.db.companies": {"id": "self", "uid": "nat", "hq_project_id": _PROJECT, "parent_id": "ref:companies.id"},
    "cloude.db.projects": {"id": "self", "uid": "nat", "company_id": "ref:companies.id", "host_key": "null",
                           "home_install_id": "null", "moved_to_install_id": "null"},
    "cloude.db.sessions": {"id": "self", "session_uuid": "nat", "claude_session_uuid": "nat", "legacy_session_id": "null",
                           "parent_session_id": _SESSION_ID, "project_id": _PROJECT, "tmux_name": "null",
                           "tmux_created_epoch": "null", "tmux_session_id": "null", "host_key": "null", "companion_of": "null"},
    "cloude.db.session_notes": {"session_uuid": _SESSION},
    "cloude.db.session_groups": {"id": "self", "group_uuid": "nat"},
    "cloude.db.session_group_styles": {"group_id": "ref:session_groups.id"},
    "cloude.db.session_group_membership": {"session_uuid": _SESSION, "group_id": "ref:session_groups.id"},
    "cloude.db.layouts": {"id": "self", "layout_uuid": "nat", "source_key": "null"},
    "cloude.db.layout_styles": {"layout_uuid": "ref:layouts.layout_uuid"},
    "cloude.db.layout_members": {"layout_id": "ref:layouts.id", "session_row_id": _SESSION_ID},
    "cloude.db.layout_broadcast_off": {"layout_id": "ref:layouts.id", "session_row_id": _SESSION_ID},
    "cloude.db.conversation_milestones": {"conversation_id": "nat", "session_uuid": _SESSION},
    "cloude.db.conversation_index": {"conversation_id": "nat", "session_uuid": _SESSION, "project_id": _PROJECT,
                                     "summary_point_id": "null"},
    "cloude.db.lineage_nodes": {"node_id": "nat"},
    "cloude.db.lineage_edges": {"parent_id": "nat", "child_id": "nat"},
    "cloude.db.agent_spawn_links": {"child_id": "nat", "child_uuid": _SESSION, "parent_id": "nat", "parent_uuid": _SESSION,
                                    "peer_install_id": "opaque", "task_message_id": "ref:work_messages.id"},
    "cloude.db.session_conversations": {"session_uuid": _SESSION, "conversation_id": "nat", "parent_conversation_id": "nat"},
    "cloude.db.mcp_events": {"caller_session_id": "null", "caller_tmux": "null"},
    "cloude.db.messaging_messages": {"session_uuid": _SESSION, "conversation_id": "nat", "binding_id": "null",
                                     "event_id": "opaque", "batch_id": "opaque"},
    "cloude.db.crosstalk_messages": {"sender_key": "opaque", "receiver_key": "opaque", "sender_id": "null", "receiver_id": "null",
                                     "sender_uuid": _SESSION, "receiver_uuid": _SESSION, "landed_session_id": "null",
                                     "thread": "opaque"},
    "cloude.db.work_items": {"id": "self", "list_key": "list", "owner_session_key": "null", "tagged_session_key": _SESSION,
                             "created_key": "opaque", "forked_from": _ITEM, "source_item_id": _ITEM,
                             "from_project_id": _PROJECT, "from_project_name": "opaque", "group_id": "ref:work_item_groups.id",
                             "inbox_id": "null", "card_parent": _ITEM, "card_holder": "null", "card_last_holder": "null",
                             "card_dealt_to": "null", "card_report_id": "null", "swarm_ref": "opaque", "card_pin_agent": "null"},
    "cloude.db.work_messages": {"item_id": _ITEM, "author_key": "opaque", "parts#files[].path": "opaque"},
    "cloude.db.work_item_lineage": {"item_id": _ITEM, "list_key": "list"},
    "cloude.db.work_card_events": {"item_id": _ITEM, "list_key": "list"},
    "cloude.db.work_blockers": {"item_id": _ITEM},
    "cloude.db.work_item_nudges": {"item_id": _ITEM},
    "cloude.db.work_item_triggers": {"item_id": _ITEM},
    "cloude.db.work_message_receipts": {"message_id": "ref:work_messages.id", "item_id": _ITEM},
    "cloude.db.work_write_actors": {"item_id": _ITEM, "actor_key": "null", "actor_session_id": "null"},
    "cloude.db.work_session_prefs": {"session_uuid": _SESSION},
    "cloude.db.work_list_prefs": {"list_key": "list"},
    "cloude.db.work_card_rules": {"list_key": "list"},
    "cloude.db.work_card_suggestions": {"list_key": "list", "card_id": _ITEM, "before_id": _ITEM, "by_agent": "null"},
    "cloude.db.work_card_deals": {"project_key": "list"},
    "cloude.db.work_inbox": {"list_key": "list", "item_ids": _ITEM},
    "cloude.db.work_item_groups": {"list_key": "list"},
    "cloude.db.work_sends": {"list_key": "list", "target": "null"},
    "cloude.db.work_held_sends": {"list_key": "list", "target": "null"},
    "cloude.db.work_project_roles": {"list_key": "list", "lead_key": _SESSION},
    "bookmarks.db.bookmarks": {"session_uuid": _SESSION, "session_row_id": _SESSION_ID, "claude_session_uuid": "nat",
                               "entry_uuid": "nat"},
    "attention_history.db.attention_events": {"session_uuid": _SESSION},
    "automations.db.automations": {"automation_id": "nat", "project_id": _PROJECT, "target#session_uuid": _SESSION,
                                   "target#project_id": _PROJECT},
    "automations.db.automation_changes": {"automation_id": "ref:automations.automation_id"},
    "automations.db.runs": {"run_id": "nat", "automation_id": "ref:automations.automation_id"},
    "automations.db.run_sessions": {"run_id": "ref:runs.run_id", "session_uuid": _SESSION, "session_row_id": _SESSION_ID},
    "stats.db.stats_annotations": {"scope_json#project": "stats"},
}

RULES: Dict[str, Dict[str, KeyRule]] = {table: {key: _parse(code) for key, code in keys.items()} for table, keys in _CODES.items()}


def rule_for(store: str, table: str, key: str) -> Optional[KeyRule]:
    return RULES.get(f"{store}.{table}", {}).get(key)

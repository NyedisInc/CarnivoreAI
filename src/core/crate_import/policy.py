
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from src.core.inventory.claims import ClaimBook

RESTORE = "restore"
RESTORE_HISTORY = "restore_history"
DERIVED = "derived"
SKIP = "skip"

S_MACHINE = "machine"
S_REINSTALL = "reinstall"
S_GRANT = "grant"
S_SECRET = "secret"
S_RETIRED = "retired"
S_SWARM = "swarm_lane"
S_NEVER = "never_imported"
S_SOURCE_RECORDS = "source_records"
S_REBUILT = "rebuilt_by_app"
S_SHADOW = "shadow_index"
S_FINAL = "final_on_import"
NOT_RESTORED = "not_restored"
NOT_YET = "not_yet"


@dataclass(frozen=True)
class Decision:

    kind: str
    reason: str = ""

    @property
    def writes(self) -> bool:
        return self.kind in (RESTORE, RESTORE_HISTORY)


def _all(kind: str, store: str, tables: str, reason: str = "") -> Dict[str, Decision]:
    return {f"{store}.{name}": Decision(kind, reason) for name in tables.split()}


MAIN = "cloude.db"
DECISIONS: Dict[str, Decision] = {
    **_all(RESTORE, MAIN, "companies projects sessions session_notes session_groups session_group_styles session_group_membership "
           "layouts layout_styles layout_members layout_broadcast_off conversation_milestones conversation_index lineage_nodes "
           "lineage_edges agent_spawn_links session_conversations work_items work_messages work_item_lineage work_card_events "
           "work_blockers work_item_nudges work_item_triggers work_message_receipts work_write_actors "
           "work_session_prefs work_list_prefs work_card_rules work_card_suggestions work_inbox work_item_groups "
           "work_sends work_project_roles"),
    **_all(RESTORE_HISTORY, MAIN, "mcp_events messaging_messages crosstalk_messages"),
    **_all(RESTORE, "bookmarks.db", "bookmarks"),
    **_all(RESTORE_HISTORY, "attention_history.db", "attention_events"),
    **_all(RESTORE, "automations.db", "automations automation_changes"),
    **_all(RESTORE_HISTORY, "automations.db", "runs run_sessions"),
    **_all(RESTORE, "stats.db", "stats_annotations"),
    **_all(SKIP, MAIN, "work_card_deals work_held_sends", S_FINAL),
    **_all(SKIP, MAIN, "pack_session_moves pack_placements peer_sessions project_storage project_replicas pack_bundle_tips "
           "pack_carried_trust pack_migrations work_callers work_reads work_send_picks", S_MACHINE),
    **_all(SKIP, MAIN, "installed_items installed_item_targets installed_loadout_members", S_REINSTALL),
    **_all(SKIP, MAIN, "crosstalk_contacts crosstalk_watches messaging_bindings messaging_notices spectator_links work_card_grants",
           S_GRANT),
    **_all(SKIP, MAIN, "work_item_waits", S_SECRET),
    **_all(SKIP, MAIN, "session_group_members transcript_archives transcript_records transcript_root_decisions message_transcripts "
           "message_appearances message_bodies", S_RETIRED),
    **_all(SKIP, MAIN, "swarm_agents swarm_wakes swarm_deliveries swarm_facts swarm_learning swarm_promotions "
           "swarm_question_askers swarm_question_hops swarm_receipts swarm_reports swarm_suggestions swarm_questions "
           "swarm_remote_bodies swarm_project_settings swarm_repo_visibility", S_SWARM),
    **_all(SKIP, MAIN, "swarm_fact_fts swarm_question_fts conversation_index_fts", S_SHADOW),
    **_all(SKIP, MAIN, "project_tombstones", S_NEVER),
    **_all(SKIP, MAIN, "export_bundles export_pointers", S_SOURCE_RECORDS),
    **_all(SKIP, MAIN, "pipeline_jobs pipeline_stage_runs transcript_files", S_REBUILT),
}


APPLY_ORDER: Tuple[str, ...] = tuple(f"{MAIN}.{name}" for name in (
    "companies", "projects", "sessions", "session_notes", "session_conversations", "conversation_index", "conversation_milestones",
    "lineage_nodes", "lineage_edges", "agent_spawn_links", "session_groups", "session_group_styles", "session_group_membership",
    "layouts", "layout_styles", "layout_members", "layout_broadcast_off"))
WORK_TABLES: Tuple[str, ...] = tuple(f"{MAIN}.{name}" for name in (
    "work_items", "work_item_groups", "work_messages", "work_inbox", "work_item_lineage", "work_card_events", "work_blockers",
    "work_item_nudges", "work_item_triggers", "work_message_receipts", "work_write_actors", "work_session_prefs", "work_list_prefs",
    "work_card_rules", "work_card_suggestions", "work_sends", "work_project_roles"))
HISTORY_TABLES: Tuple[str, ...] = tuple(f"{MAIN}.{name}" for name in ("crosstalk_messages", "mcp_events", "messaging_messages"))
SIDE_TABLES: Tuple[str, ...] = (
    "bookmarks.db.bookmarks", "attention_history.db.attention_events", "automations.db.automations", "automations.db.automation_changes",
    "automations.db.runs", "automations.db.run_sessions", "stats.db.stats_annotations")
APPLIED = frozenset(APPLY_ORDER) | frozenset(WORK_TABLES) | frozenset(HISTORY_TABLES) | frozenset(SIDE_TABLES)


def applied(store: str, table: str) -> bool:
    return f"{store}.{table}" in APPLIED


def decision_for(book: ClaimBook, store: str, table: str) -> Optional[Decision]:
    explicit = DECISIONS.get(f"{store}.{table}")
    if explicit is not None:
        return explicit
    claims = book.claims_for(store, table)
    if claims and all(c.derived for c in claims):
        return Decision(DERIVED)
    return None


from __future__ import annotations

from typing import List, Optional, Tuple

from src.core.inventory import claims as K
from src.core.inventory.claims import (BESPOKE, Claim, Exclusion, all_of, any_of, col_in, like_any, literal, via)
from src.core.inventory.model import DELETE, MAIN_STORE, SCOPE_PROJECT, SCOPE_SESSION
from src.core.inventory.scope import (APP_IDS, COMPANY_IDS, CONVERSATIONS, EARLIER_CONVERSATIONS, GRANT_SCOPES, LIST_KEYS,
                                      PRIMARY_CONVERSATIONS, PROJECT_IDS, PROJECT_ROOTS, PROJECT_UIDS, SESSION_ROW_IDS, SESSION_UUIDS)
from src.core.work import tables as T

M = MAIN_STORE
S, P = (SCOPE_SESSION,), (SCOPE_PROJECT,)
SP = (SCOPE_SESSION, SCOPE_PROJECT)


def _bespoke(table: str, keys: Tuple[str, ...] = (), paths: Tuple[str, ...] = (), purge: str = DELETE,
             scopes: Tuple[str, ...] = S, ignored: Tuple[str, ...] = (), note: str = "",
             where: Optional[K.WhereFn] = None, absent_ok: bool = False) -> Claim:
    return Claim(M, table, scopes, where, BESPOKE, keys, paths, purge, ignored=ignored, absent_ok=absent_ok, note=note)


def _node(type_column: str, id_column: str) -> K.WhereFn:
    return any_of(
        all_of(literal(f"{type_column} = 'session'"), col_in(id_column, SESSION_UUIDS)),
        all_of(literal(f"{type_column} = 'conversation'"), col_in(id_column, CONVERSATIONS)),
        all_of(literal(f"{type_column} = 'subagent'"), like_any(id_column, CONVERSATIONS, "{}/%")))


def _agents() -> K.WhereFn:
    return any_of(col_in("session_row_id", SESSION_ROW_IDS), col_in("project_id", PROJECT_IDS))


def _swarm(table: str, column: str, keys: Tuple[str, ...], paths: Tuple[str, ...] = (), note: str = "") -> Claim:
    return Claim(M, table, SP, via(M, "swarm_agents", column, "id"), keys=keys, paths=paths, note=note or "follows its agent")


def _task_manager(table: str, where: K.WhereFn, keys: Tuple[str, ...], paths: Tuple[str, ...] = (), scopes: Tuple[str, ...] = SP,
            ignored: Tuple[str, ...] = (), note: str = "", secret: Tuple[str, ...] = ()) -> Claim:
    return Claim(M, table, scopes, where, keys=keys, paths=paths, ignored=ignored, note=note, secret=secret)


def _of_items(table: str, keys: Tuple[str, ...], note: str = "follows its item", secret: Tuple[str, ...] = ()) -> Claim:
    return _task_manager(table, via(M, T.ITEMS, "item_id", "id"), keys, note=note, secret=secret)


def _of_list(table: str, keys: Tuple[str, ...], column: str = "list_key", scopes: Tuple[str, ...] = P, note: str = "") -> Claim:
    return _task_manager(table, col_in(column, LIST_KEYS), keys, scopes=scopes, note=note or "keyed by the project's list")


CLAIMS: Tuple[Claim, ...] = (
    _bespoke("sessions", ("id", "session_uuid", "claude_session_uuid", "legacy_session_id", "parent_session_id", "project_id",
                          "tmux_name", "tmux_created_epoch", "tmux_session_id", "host_key", "companion_of"), ("working_dir",),
             ignored=("tmux_socket",), note="tmux_socket names the tmux server of this Mac, not the session; companion_of is the "
             "agent row a companion shell belongs to"),
    _bespoke("session_notes", ("session_uuid",)),
    _bespoke("session_group_membership", ("session_uuid", "group_id"), where=col_in("session_uuid", SESSION_UUIDS)),
    _bespoke("session_group_members", ("tmux_name", "group_id"), note="the legacy name-keyed membership"),
    _bespoke("layout_broadcast_off", ("layout_id", "session_row_id")),
    _bespoke("layout_members", ("layout_id", "session_row_id"), where=col_in("session_row_id", SESSION_ROW_IDS)),
    _bespoke("conversation_milestones", ("conversation_id", "session_uuid")),
    _bespoke("conversation_index", ("conversation_id", "session_uuid", "project_id", "summary_point_id"), ("working_dir", "files_touched_json"),
             note="files_touched_json lists the files a conversation touched (absolute paths)"),
    _bespoke("pipeline_jobs", ("conversation_id", "session_uuid", "child_conversation_id", "point_id")),
    _bespoke("pipeline_stage_runs", ("job_id",)),
    _bespoke("transcript_files", ("conversation_id",), ("path", "root", "source_path"), ignored=("last_line_uuid", "prev_last_line_uuid"),
             note="derived ledger; an export rebuilds it; the two line uuids are positions inside the transcript"),
    _bespoke("transcript_archives", ("claude_session_uuid", "root_session_id", "project_id", "parent_archive_id",
                                     "superseded_by_archive_id"), ("source_path",), absent_ok=True, ignored=("archive_uuid",),
             note="the retired byte archive; dropped from installs that migrated past it"),
    _bespoke("transcript_records", ("archive_id",), absent_ok=True, ignored=("record_uuid", "parent_uuid"),
             note="the retired byte archive; the uuids are line ids inside the transcript"),
    _bespoke("transcript_root_decisions", ("archive_id", "root_session_id", "parent_archive_id", "project_id"), absent_ok=True,
             note="the retired byte archive"),
    _bespoke("message_transcripts", ("session_ref", "project_id"), ("source_ref", "source_path"), ignored=("host_id", "corpus_id"),
             note="the retired message corpus; host_id and corpus_id are lookup ids"),
    _bespoke("message_appearances", ("transcript_id", "body_id", "agent_id")),
    _bespoke("message_bodies", ("origin_session_ref", "message_uuid", "parent_uuid"),
             ignored=("record_type_id", "role_id", "model_id", "compact_subtype_id"),
             note="the retired message corpus; message_uuid and parent_uuid are line ids inside the transcript, the rest lookup ids"),
    Claim(M, "transcript_files", S, any_of(col_in("conversation_id", EARLIER_CONVERSATIONS), like_any("path", EARLIER_CONVERSATIONS, "%/{}.jsonl"),
                                         like_any("path", EARLIER_CONVERSATIONS, "%/{}/%")),
          keys=("conversation_id",), paths=("path", "root", "source_path"), derived=True,
          note="the ledger rows of the conversations the session ran BEFORE its current one (the purge's own claim covers the current one)"),
    Claim(M, "lineage_nodes", S, _node("node_type", "node_id"), keys=("node_id",), note="session, conversation and subagent nodes"),
    Claim(M, "lineage_edges", S, any_of(_node("parent_type", "parent_id"), _node("child_type", "child_id")),
          keys=("parent_id", "child_id"), note="an edge with either end in the subject"),
    Claim(M, "conversation_index_fts", S, covered_by="conversation_index", keys=("project_name", "session_name"),
          note="the full-text index over conversation_index; rebuilt from it"),
    Claim(M, "agent_spawn_links", S, any_of(col_in("child_uuid", SESSION_UUIDS), col_in("parent_uuid", SESSION_UUIDS),
                                          col_in("child_id", APP_IDS), col_in("parent_id", APP_IDS)),
          keys=("child_id", "child_uuid", "parent_id", "parent_uuid", "peer_install_id", "task_message_id"), note="who spawned whom; task_message_id is a Task Manager message"),
    Claim(M, "crosstalk_messages", S, any_of(col_in("sender_uuid", SESSION_UUIDS), col_in("receiver_uuid", SESSION_UUIDS),
                                           col_in("sender_key", SESSION_UUIDS), col_in("receiver_key", SESSION_UUIDS),
                                           col_in("sender_id", APP_IDS), col_in("receiver_id", APP_IDS),
                                           col_in("landed_session_id", APP_IDS)),
          keys=("sender_key", "receiver_key", "sender_id", "receiver_id", "sender_uuid", "receiver_uuid", "landed_session_id", "thread"),
          ignored=("delivery_path",), note="a message is the subject's when either end is; thread groups a reply chain"),
    Claim(M, "crosstalk_contacts", S, any_of(col_in("left_key", SESSION_UUIDS), col_in("right_key", SESSION_UUIDS)),
          keys=("pair_key", "left_key", "right_key"), note="the grant between two panes"),
    Claim(M, "crosstalk_watches", S, any_of(col_in("watcher_key", SESSION_UUIDS), col_in("target_key", SESSION_UUIDS),
                                          col_in("watcher_id", APP_IDS), col_in("target_id", APP_IDS)),
          keys=("watcher_key", "watcher_id", "target_key", "target_id")),
    Claim(M, "mcp_events", S, any_of(col_in("caller_session_id", SESSION_UUIDS), col_in("caller_session_id", APP_IDS)),
          keys=("caller_session_id", "caller_tmux"), ignored=("call_id",),
          note="telemetry of tool calls; caller_tmux is a name, never matched on; call_id is the call's own id"),
    Claim(M, "messaging_bindings", S, col_in("session_uuid", SESSION_UUIDS), keys=("session_uuid", "conversation_id"),
          note="conversation_id here is a MESSAGING conversation, not an agent's"),
    Claim(M, "messaging_messages", S, col_in("session_uuid", SESSION_UUIDS),
          keys=("session_uuid", "conversation_id", "binding_id", "event_id", "batch_id"), ignored=("provider_id", "provider_message_id"),
          note="conversation_id here is a MESSAGING conversation, not an agent's; provider ids belong to the chat provider"),
    Claim(M, "messaging_notices", S, via(M, "messaging_bindings", "conversation_id", "conversation_id"), keys=("conversation_id",),
          note="follows the subject's messaging bindings"),
    Claim(M, "session_conversations", S, col_in("session_uuid", SESSION_UUIDS), keys=("session_uuid", "conversation_id", "parent_conversation_id"),
          absent_ok=True, note="present only on installs that ran the build that created it; no current code writes it"),
    Claim(M, "export_pointers", S, col_in("conversation_id", CONVERSATIONS), keys=("conversation_id", "bundle_id"),
          note="which export bundle holds a conversation (the exported status, step 4; docs/export-status.md)"),
    Claim(M, "export_bundles", SP, any_of(col_in("project_uid", PROJECT_UIDS), col_in("session_uuid", SESSION_UUIDS),
                                          via(M, "export_pointers", "bundle_id", "bundle_id")),
          keys=("bundle_id", "project_uid", "session_uuid"),
          note="an export bundle's record; the bundle file itself lives outside Carnivore"),
    Claim(M, "spectator_links", S, col_in("session_id", APP_IDS), keys=("session_id",),
          secret=("token_sha256", "link_nonce"), note="share links to a session; the token hash is a secret and the link is re-minted, never carried"),
    Claim(M, "session_groups", S, via(M, "session_group_membership", "id", "group_id"), keys=("id", "group_uuid"),
          note="the groups the subject's membership rows point at"),
    Claim(M, "session_group_styles", S, via(M, "session_groups", "group_id", "id"), keys=("group_id",)),
    Claim(M, "layouts", S, via(M, "layout_members", "id", "layout_id"), keys=("id", "layout_uuid", "source_key"),
          note="the layouts the subject's member rows point at"),
    Claim(M, "layout_styles", S, via(M, "layouts", "layout_uuid", "layout_uuid"), keys=("layout_uuid",)),
    Claim(M, "swarm_agents", SP, _agents(), keys=("id", "parent_id", "project_id", "company_id", "session_row_id", "host_key", "thread_key",
                                                  "origin_message_ref"),
          paths=("repo_dir",), note="an agent whose body is the session, or that belongs to the project"),
    _swarm("swarm_wakes", "agent_id", ("agent_id", "conversation_uuid", "tmux_name", "tmux_epoch")),
    _swarm("swarm_deliveries", "agent_id", ("agent_id", "wake_id", "source_ref", "owner_message_ref"),
           note="follows its agent; the refs point into the Task Manager"),
    _swarm("swarm_facts", "agent_id", ("agent_id", "taught_by_agent_id", "owner_message_ref"), ("rel_path",)),
    Claim(M, "swarm_fact_fts", SP, covered_by="swarm_facts", keys=("agent_id",), note="the full-text index over swarm_facts; rebuilt"),
    _swarm("swarm_learning", "agent_id", ("agent_id", "question_id", "owner_message_ref", "delivered_wake_id")),
    _swarm("swarm_promotions", "agent_id", ("agent_id", "project_id", "receipt_card_ref"), ("seed_rel_path",)),
    _swarm("swarm_question_askers", "agent_id", ("question_id", "agent_id", "crosstalk_message_id"), ("author_path",)),
    _swarm("swarm_question_hops", "agent_id", ("question_id", "agent_id")),
    _swarm("swarm_receipts", "answering_agent_id", ("question_id", "answering_agent_id")),
    _swarm("swarm_reports", "agent_id", ("agent_id", "parent_id", "child_card_ref", "parent_card_ref")),
    _swarm("swarm_suggestions", "by_agent_id", ("by_agent_id", "company_id", "made_project_id", "card_ref", "owner_message_ref")),
    Claim(M, "swarm_questions", SP, via(M, "swarm_question_askers", "id", "question_id"), keys=("id", "card_ref", "answer_message_ref"),
          note="the questions the subject's agents asked"),
    Claim(M, "swarm_question_fts", SP, covered_by="swarm_questions", keys=("question_id",), note="the full-text index over swarm_questions; rebuilt"),
    Claim(M, "swarm_remote_bodies", SP, any_of(col_in("session_row_id", SESSION_ROW_IDS), col_in("project_uid", PROJECT_UIDS)),
          keys=("session_row_id", "home_agent_id", "project_uid", "home_install_id"), paths=("mirror_dir",)),
    Claim(M, "swarm_project_settings", P, col_in("project_id", PROJECT_IDS), keys=("project_id",)),
    Claim(M, "swarm_repo_visibility", P, col_in("repo_dir", PROJECT_ROOTS), paths=("repo_dir",), keys=("card_ref",),
          note="the visibility check of the project's folder as a git repo"),
    Claim(M, "pack_session_moves", S, any_of(col_in("session_uuid", SESSION_UUIDS), col_in("claude_session_uuid", PRIMARY_CONVERSATIONS)),
          keys=("id", "session_uuid", "claude_session_uuid", "source_install_id", "target_install_id")),
    Claim(M, "pack_placements", S, col_in("session_id", SESSION_ROW_IDS), keys=("agent_id", "session_id", "chosen_install_id"),
          note="session_id is a sessions.id"),
    Claim(M, "peer_sessions", S, col_in("session_id", APP_IDS), keys=("host_key", "peer_session_uuid", "peer_row_id", "session_id"),
          note="shadow rows of sessions on paired computers"),
    Claim(M, "pack_rollups", S, col_in("conversation_id", CONVERSATIONS), keys=("peer_install_id", "conversation_id", "project"),
          derived=True, note="usage rolled up from a paired computer; re-pulled"),
    Claim(M, "pack_rollup_counters", S, col_in("conversation_id", CONVERSATIONS), keys=("peer_install_id", "conversation_id", "project"),
          derived=True, note="usage counters rolled up from a paired computer; re-pulled"),
    Claim(M, "projects", P, col_in("id", PROJECT_IDS), keys=("id", "uid", "company_id", "host_key", "home_install_id",
                                                              "moved_to_install_id"), paths=("root", "raw_path"),
          ignored=("github_account",), note="the project row itself"),
    Claim(M, "companies", P, col_in("id", COMPANY_IDS), keys=("id", "uid", "hq_project_id", "parent_id"),
          note="the project's company; shared with its sibling projects, so a purge never removes it"),
    Claim(M, "project_tombstones", P, col_in("root", PROJECT_ROOTS), paths=("root",)),
    Claim(M, "project_storage", P, col_in("project_id", PROJECT_IDS), keys=("project_id", "job_id"), paths=("archive_name",),
          note="the packed archive's record"),
    Claim(M, "project_replicas", P, col_in("project_uid", PROJECT_UIDS), keys=("project_uid", "install_id"), paths=("root",)),
    Claim(M, "pack_bundle_tips", P, col_in("project_uid", PROJECT_UIDS), keys=("project_uid", "install_id")),
    Claim(M, "pack_carried_trust", P, any_of(col_in("project_uid", PROJECT_UIDS), col_in("folder", PROJECT_ROOTS)),
          keys=("project_uid", "source_install_id", "op_id"), paths=("folder",)),
    Claim(M, "pack_migrations", P, col_in("subject_uid", PROJECT_UIDS), keys=("id", "parent_id", "subject_uid", "source_install_id",
                                                                           "target_install_id"),
          note="the project's migration history between computers"),
    Claim(M, "installed_items", P, col_in("project_path", PROJECT_ROOTS), keys=("install_id", "item_id"), paths=("project_path",),
          ignored=("publisher_key_id",), note="catalog items installed for this project's folder; publisher_key_id is the publisher's signing key"),
    Claim(M, "installed_item_targets", P, via(M, "installed_items", "install_id", "install_id"), keys=("install_id",), paths=("path",)),
    Claim(M, "installed_loadout_members", P, via(M, "installed_items", "install_id", "install_id"), keys=("install_id", "item_id", "member_install_id")),
    Claim(M, "conversation_index", P, all_of(col_in("project_id", PROJECT_IDS),
                                              literal("session_uuid NOT IN (SELECT session_uuid FROM sessions)")),
          keys=("conversation_id", "session_uuid", "project_id"), paths=("working_dir", "files_touched_json"),
          note="the project's index rows whose session row is gone (the rest are the sessions' own)"),
    _task_manager(T.ITEMS, any_of(col_in("owner_session_key", SESSION_UUIDS), col_in("tagged_session_key", SESSION_UUIDS),
                            col_in("list_key", LIST_KEYS)),
            ("id", "list_key", "owner_session_key", "tagged_session_key", "created_key", "forked_from", "source_item_id",
             "from_project_id", "from_project_name", "group_id", "inbox_id", "card_parent", "card_holder", "card_last_holder",
             "card_dealt_to", "card_report_id", "swarm_ref", "card_pin_agent"),
            note="a session's items are the ones it owns or is tagged on; a project's are its list's. created_key (authorship, "
                 "set on most items) is deliberately not matched: authorship is project-owned, so a session's inventory does "
                 "not claim every item it merely wrote. card_ref columns in the Swarm tables point into these items"),
    _task_manager(T.MESSAGES, via(M, T.ITEMS, "item_id", "id"), ("item_id", "author_key"), ("parts#files[].path",),
            note="the files a message carries are stored under files/<item id>/ and named in parts"),
    _of_items(T.ITEM_LINEAGE, ("item_id", "list_key")),
    _of_items(T.CARD_EVENTS, ("item_id", "list_key")),
    _of_items(T.BLOCKERS, ("item_id",)),
    _of_items(T.ITEM_NUDGES, ("item_id",)),
    _of_items(T.ITEM_TRIGGERS, ("item_id",)),
    _of_items(T.ITEM_WAITS, ("item_id",), note="follows its item; token_hash is the hash of the wait's answer token, never exported",
              secret=("token_hash",)),
    _of_items(T.MESSAGE_RECEIPTS, ("message_id", "item_id")),
    _task_manager(T.WRITE_ACTORS, any_of(via(M, T.ITEMS, "item_id", "id"), col_in("actor_session_id", SESSION_UUIDS), col_in("actor_session_id", APP_IDS)),
            ("item_id", "actor_key", "actor_session_id"), ignored=("cross_project",),
            note="who wrote each row; a session's writes count even on other items"),
    _task_manager(T.CALLERS, any_of(col_in("session_id", SESSION_UUIDS), col_in("session_id", APP_IDS), col_in("list_key", LIST_KEYS)), ("session_id", "list_key"),
            note="the last Task Manager tool caller per list"),
    _task_manager(T.READS, any_of(col_in("session_id", SESSION_UUIDS), col_in("session_id", APP_IDS), col_in("list_key", LIST_KEYS)), ("session_id", "list_key"),
            note="how far each session has read each list"),
    _task_manager(T.SESSION_PREFS, col_in("session_uuid", SESSION_UUIDS), ("session_uuid",), scopes=S, note="per-session nudge and do-not-disturb"),
    _of_list(T.LIST_PREFS, ("list_key",)),
    _of_list(T.CARD_RULES, ("list_key",)),
    _of_list(T.CARD_SUGGESTIONS, ("list_key", "card_id", "before_id", "by_agent")),
    _of_list(T.CARD_DEALS, ("project_key",), "project_key"),
    _of_list(T.INBOX, ("list_key", "item_ids")),
    _of_list(T.ITEM_GROUPS, ("list_key",)),
    _of_list(T.TELLS, ("list_key", "target")),
    _of_list(T.HELD_SENDS, ("list_key", "target"), note="a tell held back until its target can take it (#1890); keyed by the project's list, like tells"),
    _of_list(T.TELL_PICKS, ("list_key", "target_key")),
    _of_list(T.PROJECT_ROLES, ("list_key", "lead_key")),
    _task_manager(T.CARD_GRANTS, col_in("scope", GRANT_SCOPES), ("scope",), scopes=P, note="the project's card slots (scope project:<id>)"),
)

_REASON_RETIRED_CORPUS = ("the retired message archive corpus (schema kept dormant, Alex (example-owner) 2026-10-12, #1680): nothing "
                          "writes it, and purge handles the transcripts, appearances and bodies it hangs off")
_REASON_RETIRED_SEARCH = ("the retired search schema (session_search_* in carnivore.db): the live index is deepsearch.db; "
                          "purge never touches these copies")


_IGNORED = {
    "catalog_index_state": ("index_key_id",), "catalog_revocations_seen": ("index_key_id",),
    "blueprints": ("blueprint_uuid",), "computer_links": ("peer_install_id",),
    "federation_grants": ("grant_id", "peer_install_id", "public_key", "remote_grant_id"),
    "hosts": ("tmux_path", "tmux_version", "login_path", "machine_id", "peer_install_id", "peer_grant_id", "computer_install_id"),
    "item_settings": ("item_id",), "message_projection_ledger": ("source_path", "source_ref", "archive_id", "transcript_id"), "lineage_sources": ("transcript_id",),
    "message_body_block_status": ("body_id",), "message_content_blocks": ("body_id", "block_type_id", "tool_use_id"),
    "message_corpora": ("host_id", "corpus_key", "root_path"), "message_hosts": ("machine_id",),
    "message_ingest_findings": ("subject_id",), "message_projects": ("corpus_id", "observed_cwd"),
    "message_secret_findings": ("body_id",), "messaging_conversations": ("provider_id", "match_key"),
    "migration_trail": ("entry_uuid", "backup_path"), "pack_blobs": ("blob_id", "peer_install_id", "path"),
    "pack_machines": ("install_id", "host_key"), "pack_relay_targets": ("account_key", "target_install_id"),
    "pack_rollup_state": ("peer_install_id",), "session_search_docs": ("conversation_id", "point_id"),
    "session_search_live": ("conversation_id", "path", "base_point_id"), "session_search_rows": ("doc_id", "live_id"),
}


def _excl(table: str, kind: str, reason: str, absent_ok: bool = False) -> Exclusion:
    return Exclusion(M, table, kind, reason, absent_ok, _IGNORED.get(table, ()))


EXCLUSIONS: Tuple[Exclusion, ...] = (
    _excl("app_alerts", K.UNKEYED, "alerts about the app itself"),
    _excl("archive_project_overlay", K.DORMANT, "the retired archive's presentation overlay (schema v19): names, groups and hidden flags for archive projects",
          absent_ok=True),
    _excl("blueprints", K.GLOBAL, "reusable Swarm blueprints, owned by the install, not by a project or session"),
    _excl("browser_sessions", K.UNKEYED, "the in-app browser's tabs"),
    _excl("catalog_index_state", K.UNKEYED, "catalog index verification state"),
    _excl("catalog_revocations_seen", K.UNKEYED, "catalog revocation list state"),
    _excl("computer_links", K.GLOBAL, "paired-computer links and their certificates: machine identity, never carried between installs"),
    _excl("federation_grants", K.GLOBAL, "the grants this install made to paired computers: machine trust, never carried"),
    _excl("hosts", K.GLOBAL, "the computers this install knows, with their tool paths and probe state"),
    _excl("item_settings", K.GLOBAL, "per catalog item settings of this install"),
    _excl("lineage_sources", K.DERIVED, "the lineage extraction ledger, keyed by archive transcript ids; rebuilt from the transcripts"),
    _excl("messaging_conversations", K.GLOBAL, "external chat threads and their providers; the subject's bindings and messages are claimed"),
    _excl("messaging_providers", K.GLOBAL, "chat providers of this install, with cursors and credentials references"),
    _excl("meta", K.GLOBAL, "install id and schema version: read on import to check compatibility, never copied"),
    _excl(T.META, K.UNKEYED, "the Task Manager's change sequence counter and its work ladder version, no subject"),
    _excl(T.IMPORTS, K.GLOBAL, "the record of the one-way import from huddle.db (issue #1711, P2): counts and digests, no subject rows"),
    _excl("migration_trail", K.GLOBAL, "the datastore's own schema history, with its backup paths"),
    _excl("message_projection_ledger", K.DORMANT, _REASON_RETIRED_CORPUS, absent_ok=True),
    _excl("pack_blobs", K.TRANSIENT, "files in flight between paired computers"),
    _excl("pack_machines", K.GLOBAL, "the Pack of computers: machine specs and membership"),
    _excl("pack_relay_targets", K.GLOBAL, "which paired computers receive which account's access token"),
    _excl("pack_rollup_state", K.GLOBAL, "the usage rollup's pull cursor per paired computer"),
    _excl("pack_spawn_queue", K.TRANSIENT, "queued spawn requests waiting for a computer"),
    _excl("session_search_docs", K.DORMANT, _REASON_RETIRED_SEARCH),
    _excl("session_search_fts", K.DORMANT, _REASON_RETIRED_SEARCH),
    _excl("session_search_live", K.DORMANT, _REASON_RETIRED_SEARCH),
    _excl("session_search_rows", K.DORMANT, _REASON_RETIRED_SEARCH),
    *(_excl(t, K.DORMANT, _REASON_RETIRED_CORPUS) for t in (
        "message_block_search", "message_block_types", "message_body_block_status", "message_compact_subtypes",
        "message_content_blocks", "message_corpora", "message_hosts", "message_ingest_findings", "message_models",
        "message_projects", "message_record_types", "message_roles",
        "message_secret_findings")),
)


def claims() -> List[Claim]:
    return list(CLAIMS)


def exclusions() -> List[Exclusion]:
    return list(EXCLUSIONS)

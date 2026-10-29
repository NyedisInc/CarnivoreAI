
from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from src.core.inventory import claims as K
from src.core.inventory.claims import BESPOKE, Claim, ExcludedStore, Exclusion, any_of, col_in, json_field_in, json_target_in, like_any, via
from src.core.inventory.model import DELETE, SCOPE_PROJECT, SCOPE_SESSION
from src.core.inventory.scope import (APP_IDS, CONVERSATIONS, PROJECT_IDS, PROJECT_ROOTS, SESSION_ROW_IDS,
                                      SESSION_UUIDS, STATS_PROJECTS)

BOOKMARKS = "bookmarks.db"
ATTENTION = "attention_history.db"
AUTOMATIONS = "automations.db"
DEEPSEARCH = "deepsearch.db"
STATS = "stats.db"
READER_STATE = "reader_state.db"
SKILL_FIRES = "skill_fires.db"

SIDE_DBS: Dict[str, str] = {
    BOOKMARKS: "bookmarks.db", ATTENTION: "attention_history.db",
    AUTOMATIONS: "automations/automations.db", DEEPSEARCH: "deepsearch.db",
    STATS: "pipeline-plugins/stats.db", READER_STATE: "reader_state.db", SKILL_FIRES: "skill_fires.db",
}

S, P = (SCOPE_SESSION,), (SCOPE_PROJECT,)
SP = (SCOPE_SESSION, SCOPE_PROJECT)
CONVERSATION_PATHS = any_of(like_any("path", CONVERSATIONS, "%/{}.jsonl"), like_any("path", CONVERSATIONS, "%-{}.jsonl"),
                            like_any("path", CONVERSATIONS, "%/{}/%"))


def side_db_path(state_dir: Path, store: str) -> Path:
    return Path(state_dir) / SIDE_DBS[store]


def _bespoke(store: str, table: str, keys: Tuple[str, ...], paths: Tuple[str, ...] = (), derived: bool = False,
             scopes: Tuple[str, ...] = S, note: str = "", ignored: Tuple[str, ...] = ()) -> Claim:
    return Claim(store, table, scopes, None, BESPOKE, keys, paths, DELETE, derived, ignored=ignored, note=note)


CLAIMS: Tuple[Claim, ...] = (
    _bespoke(BOOKMARKS, "bookmarks", ("session_uuid", "session_row_id", "claude_session_uuid", "entry_uuid")),
    _bespoke(ATTENTION, "attention_events", ("session_uuid",)),
    _bespoke(DEEPSEARCH, "session_search_live", ("conversation_id",), ("path",), derived=True,
             ignored=("base_point_id",), note="one row per indexed transcript file; its rows and postings go with it (base_point_id is the marker 'vault': the file is gone and the backup vault serves it)"),
    *(Claim(store, "plugin_cursors", S, col_in("conversation_id", CONVERSATIONS), keys=("conversation_id",), paths=("path",),
            derived=True, note="the pipeline's read cursor per transcript file; rebuilt by reading the file again")
      for store in (DEEPSEARCH, STATS)),
    Claim(DEEPSEARCH, "session_search_rows", S, covered_by="session_search_live", derived=True, ignored=("doc_id", "live_id"),
          note="byte offsets into the transcript; rebuilt on import, never copied"),
    Claim(DEEPSEARCH, "session_search_fts", S, covered_by="session_search_live", derived=True, note="the postings of session_search_rows"),
    Claim(DEEPSEARCH, "session_search_folders", S, covered_by="session_search_live", paths=("folder",), derived=True, ignored=("live_id",),
          note="the folders a live file was found in"),
    Claim(AUTOMATIONS, "automations", SP, any_of(col_in("project_id", PROJECT_IDS), json_target_in("target", ("session_uuid",), SESSION_UUIDS),
                                                json_target_in("target", ("project_id",), PROJECT_IDS),
                                                json_target_in("target", ("folder",), PROJECT_ROOTS)),
          keys=("automation_id", "project_id", "target#session_uuid", "target#project_id"), paths=("target#folder",),
          note="automations scoped to the project, or whose target (or a sequence step) names the session, the project or its folder"),
    Claim(AUTOMATIONS, "automation_changes", SP, via(AUTOMATIONS, "automations", "automation_id", "automation_id"), keys=("automation_id",)),
    Claim(AUTOMATIONS, "runs", SP, via(AUTOMATIONS, "automations", "automation_id", "automation_id"), keys=("run_id", "automation_id"),
          ignored=("sessions", "boot_id"), note="a run's sessions column lists the session uuids it woke; boot_id is the server boot that ran it"),
    Claim(AUTOMATIONS, "run_sessions", SP, any_of(col_in("session_uuid", SESSION_UUIDS), col_in("session_row_id", SESSION_ROW_IDS),
                                                 via(AUTOMATIONS, "runs", "run_id", "run_id")),
          keys=("run_id", "session_uuid", "session_row_id")),
    Claim(STATS, "dim_source", S, col_in("conversation_id", CONVERSATIONS), keys=("conversation_id", "parent_conversation_id"),
          ignored=("path_key", "account_id"), derived=True,
          note="one row per transcript file the stats read; path_key is an interned path, account_id this install's account"),
    Claim(STATS, "dim_live", S, any_of(col_in("conversation_id", CONVERSATIONS), like_any("conversation_id", APP_IDS, "session:{}")),
          keys=("conversation_id", "project"), derived=True,
          note="a live-sampled row names a conversation, or ``session:<app id>`` for a shell with no transcript"),
    Claim(STATS, "dim_project", P, col_in("name", STATS_PROJECTS), keys=("name",), derived=True,
          note="usage is keyed by an opaque project key, sha256(realpath(folder))[:24], so a relocated import must remap it"),
    Claim(STATS, "rollup_rev", S, col_in("conversation_id", CONVERSATIONS), keys=("conversation_id",), derived=True,
          note="the Pack rollup's revision stamp per conversation and hour; restamped on import"),
    Claim(STATS, "stats_git_markers", P, col_in("project", STATS_PROJECTS), keys=("project",), ignored=("commit_id",), derived=True,
          note="rule-file commits seen for the project's folder; rebuilt from git"),
    Claim(STATS, "stats_git_progress", P, col_in("project", STATS_PROJECTS), keys=("project",), derived=True,
          note="how far the rule-file history walk got for the project's folder"),
    Claim(STATS, "stats_annotations", P, json_field_in("scope_json", "project", STATS_PROJECTS), keys=("scope_json#project",),
          note="chart annotations; a rule-change annotation is scoped to the project's stats key in scope_json"),
    *(Claim(STATS, table, SP, any_of(via(STATS, "dim_source", "src", "id"), via(STATS, "dim_project", "project", "id")),
            keys=("src", "project"), derived=True, note="usage rows of the subject's transcripts or project")
      for table in ("usage_minute", "usage_hour", "counter_minute", "counter_hour")),
    Claim(STATS, "file_state", S, via(STATS, "dim_source", "src", "id"), keys=("src",), derived=True),
    *(Claim(STATS, table, S, via(STATS, "dim_live", "live", "id"), keys=("live",), derived=True)
      for table in ("activity_minute", "activity_hour")),
    Claim(READER_STATE, "reader_state", S, CONVERSATION_PATHS, keys=("reader",), paths=("path",), derived=True,
          note="resume points into transcript files; rebuilt"),
    Claim(SKILL_FIRES, "skill_fires", S, any_of(CONVERSATION_PATHS, col_in("session_key", CONVERSATIONS)), keys=("session_key",),
          paths=("path",), derived=True, note="skill invocations found in transcripts; rebuilt"),
    Claim(SKILL_FIRES, "skill_fire_cursors", S, CONVERSATION_PATHS, paths=("path",), derived=True),
)

_STATS_GLOBAL = "usage and activity dictionaries and time series with no subject; the stats rebuild them from the transcripts"


def _excl(store: str, table: str, kind: str, reason: str, ignored: Tuple[str, ...] = ()) -> Exclusion:
    return Exclusion(store, table, kind, reason, ignored=ignored)


EXCLUSIONS: Tuple[Exclusion, ...] = (
    _excl(AUTOMATIONS, "seed_tombstones", K.GLOBAL, "which built-in automations the owner deleted: install configuration"),
    _excl(DEEPSEARCH, "cache_meta", K.GLOBAL, "the cache's build state"),
    *(_excl(DEEPSEARCH, f"session_search_fts_{s}", K.SHADOW, "internal tables of the session_search_fts index") for s in ("config", "data", "docsize", "idx")),
    *(_excl(STATS, t, K.DERIVED, _STATS_GLOBAL) for t in (
        "stats_meta", "stats_events", "stats_models_seen", "price_versions", "stat_retention", "dim_model", "dim_key",
        "dim_counter", "dim_price", "coverage_minute", "coverage_hour")),
    *(_excl(STATS, t, K.DERIVED, "the provider quota windows by this install's account id; polled again", ("account_id",))
      for t in ("quota_minute", "quota_hour")),
    _excl(READER_STATE, "meta", K.UNKEYED, "the reader state schema version"),
    *(_excl(store, "plugin_meta", K.UNKEYED, "the pipeline framework's schema version and creation time for this plugin database")
      for store in (DEEPSEARCH, STATS)),
    _excl(STATS, "rollup_meta", K.UNKEYED, "the Pack rollup's revision counter"),
    _excl(STATS, "stats_answers", K.DERIVED, "the cache of computed answers to stats queries, keyed by a query fingerprint; recomputed on demand"),
    _excl(STATS, "stats_backfill", K.GLOBAL, "backfill requests of this install, keyed by an idempotency token; closed at startup",
          ("idempotency_key",)),
    _excl(STATS, "stats_charts", K.GLOBAL, "the owner's chart definitions: install configuration"),
    _excl(STATS, "stats_disabled_spans", K.GLOBAL, "the spans while stats were switched off: install configuration"),
    _excl(STATS, "stats_rule_sources", K.DERIVED, "the digest of each rule file last seen, keyed by a hash of the file's path; rebuilt by the next observation",
          ("source_key",)),
    _excl(STATS, "stats_settings", K.GLOBAL, "the stats on/off switch: install configuration"),
    _excl(STATS, "stats_tripwires", K.GLOBAL, "the owner's alert thresholds on stats queries: install configuration", ("chart_id",)),
)

EXCLUDED_STORES: Tuple[ExcludedStore, ...] = (
    ExcludedStore("refresh_tokens.db", K.SECRET, "credentials: never exported, never listed"),
    ExcludedStore("spectator_link_tokens.db", K.SECRET, "credentials: never exported, never listed"),
    ExcludedStore("catalog_tokens.db", K.SECRET, "credentials: never exported, never listed"),
    ExcludedStore("hook_tokens.json", K.SECRET, "credentials: never exported, never listed"),
    ExcludedStore("mcp_tokens.json", K.SECRET, "credentials: never exported, never listed"),
    ExcludedStore("agent_actions.db", K.TRANSIENT, "pending and recent approval cards: a card expires, and its body names sessions only for the moment it is open"),
    ExcludedStore("byoai.db", K.GLOBAL, "the call log of the install's own AI connections: keyed by connection and feature, not by session or project"),
    ExcludedStore("summary_spend.db", K.GLOBAL, "a spend ledger by engine and day, no subject"),
    ExcludedStore("mcp_usage.db", K.GLOBAL, "daily MCP tool counts by tool, no subject"),
    ExcludedStore("phone_link.db", K.GLOBAL, "phone pairing of this install"),
    ExcludedStore("skill_watch.db", K.GLOBAL, "skill drift baselines of this install"),
    ExcludedStore("cplugs/activity.db", K.GLOBAL, "the audit log of plugin calls, keyed by plugin id"),
    ExcludedStore("cplugs/ai_budget.db", K.GLOBAL, "daily AI budget per plugin feature"),
    ExcludedStore("cplugs/egress.db", K.GLOBAL, "network egress log per plugin"),
    ExcludedStore("purge-receipts", K.GLOBAL, "the receipts of past purges: kept forever on purpose; ids and counts only, no text"),
    ExcludedStore("cplugs/huddle/huddle.db", K.DORMANT, "the read-only leftover of the one-way import into carnivore.db's work_ tables "
                  "(issue #1711, P2): the rollback source for one release, never written again; IMPORTED.json beside it"),
    ExcludedStore("cplugs/huddle/IMPORTED.json", K.DORMANT, "the record of the one-way import beside the read-only huddle.db leftover: "
                  "counts and the source digest, no subject rows"),
    ExcludedStore("addons/huddle/huddle.db", K.DORMANT, "the Task Manager's database before it moved to cplugs/huddle (the folder keeps a .moved-to-cplugs marker)"),
    ExcludedStore("cplugs/mcpondemand/mcpondemand.db", K.DORMANT, "the call journal of the parked MCP on-demand surface B (#1948): its plugin is gone and nothing writes it"),
    ExcludedStore("ai_summaries.db", K.DORMANT, "the summarize plugin's leftover (the plugin and the working-on line were removed in #1898): never opened, "
                  "traced or written again; kept on disk untouched"),
    ExcludedStore("addons/state.json", K.GLOBAL, "which add-ons are on, with their grants and settings: install configuration"),
    ExcludedStore("cplugs/state.json", K.GLOBAL, "which plugins are on, with their grants and settings: install configuration"),
    ExcludedStore("carnivore.online-backup.db", K.DERIVED, "an online copy of carnivore.db taken by the backup; the live rows are the claimed ones"),
    ExcludedStore("session-journal/pre-reboot-*.db", K.DERIVED, "copies of carnivore.db taken before a reboot; the live rows are the claimed ones"),
    ExcludedStore("automations-scheduler.jsonl", K.GLOBAL, "the automation scheduler's own log"),
    ExcludedStore("backup-health-tm-misses.json", K.GLOBAL, "a counter of the backup health check"),
    ExcludedStore("browser_pages.json", K.GLOBAL, "the in-app browser's open pages: keyed by page, not by session"),
    ExcludedStore("catalog_theme_palettes/*", K.GLOBAL, "theme palettes cached by content hash"),
    ExcludedStore("corpus-ingest/*", K.GLOBAL, "run logs and scan caches of the retired corpus ingest"),
    ExcludedStore("db-integrity/*", K.GLOBAL, "the database integrity verdict"),
    ExcludedStore("debug/*", K.GLOBAL, "the app's own debug trace"),
    ExcludedStore("history-backup/*", K.GLOBAL, "the history backup's runs, proof and staging manifest"),
    ExcludedStore("message-drain/*", K.GLOBAL, "state of the retired message drain"),
    ExcludedStore("message-projection/*", K.GLOBAL, "state of the retired message projection"),
    ExcludedStore("migration_trail.jsonl", K.GLOBAL, "the datastore's schema history, with its backup paths"),
    ExcludedStore("notification_source_state.json", K.GLOBAL, "which notification sources fired last"),
    ExcludedStore("open_files.json", K.GLOBAL, "the files list of the app's file viewer"),
    ExcludedStore("save-pipeline-runner.json", K.GLOBAL, "the save pipeline runner's process record"),
    ExcludedStore("save-catchup-state.json", K.GLOBAL, "the save catch-up check's counters"),
    ExcludedStore("server-log-location.json", K.GLOBAL, "where the server writes its log"),
    ExcludedStore("recovered-transcripts/*", K.GLOBAL, "transcripts recovered from foreign archives, filed by their own paths; not a session's files"),
    ExcludedStore("row_looks.json", K.GAP, "sidebar row colors and icons keyed by an opaque look id that derives from the row"),
    ExcludedStore("session_metadata.json", K.GAP, "a legacy single-session snapshot (id, pid, working directory)"),
    ExcludedStore("lineage-live.json", K.GAP, "the live lineage scan's index, keyed by transcript path; rebuilt by the scan"),
    ExcludedStore("company_images/*", K.GAP, "generated company images, keyed by company id"),
    ExcludedStore("project_images/*", K.GAP, "generated project images, keyed by project id"),
)


def claims() -> Tuple[Claim, ...]:
    return CLAIMS


def exclusions() -> Tuple[Exclusion, ...]:
    return EXCLUSIONS


def excluded_stores() -> Tuple[ExcludedStore, ...]:
    return EXCLUDED_STORES

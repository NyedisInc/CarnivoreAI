
from __future__ import annotations

from src.core.boot.catalog import build_registry
from src.core.boot.steps import FailureMode

START_ORDER = [
    "mcp_old_name_counter", "config_migrations", "datastore", "work_store", "pack_job_recovery", "core_services",
    "cli_command_shim", "server_log_breadcrumb", "server_log_rotate", "log_monitor", "auth_config",
    "projects_config_migration", "first_run_import", "notifications", "claude_hooks_strip", "local_servers",
    "log_monitoring", "refresh_store", "spectator_links_store", "refresh_purge_loop", "app_state_components", "relay",
    "phone_link", "app_state_preferences", "deepsearch_scope", "event_hub", "pushes", "pack_orphan_ops",
    "companion_reconcile", "dev_hooks", "app_alerts", "account_notice", "self_check", "transcript_manifest", "pipeline",
    "browsers", "upload_sweeper", "skill_sweeper", "pipe_pruner", "skill_journal_recovery", "skill_auto_update",
    "mac_awake", "crosstalk_dispatcher", "messaging", "attention_watcher", "notify_sources", "listing_push", "auto_sleep",
    "mcp_bridge_migration", "automations", "work_backfill", "late_watches", "update_checker", "update_checker_route",
    "provider_ledger_poller", "db_integrity_scheduler", "db_integrity_scheduler_start", "session_journal",
    "lineage_live", "stats", "ready_announcement", "federation_discovery", "byoai_features", "federation_link",
    "plugin_host", "sidecar_runtime", "crosstalk_card_push", "gc_tuning", "request_log_rollup", "engine_clients",
]

STOP_ORDER = [
    "request_log_rollup", "sidecar_runtime", "plugin_host", "crosstalk_card_push", "federation_link",
    "federation_discovery", "update_checker", "lineage_live", "account_notice", "self_check", "transcript_manifest",
    "app_alerts", "pipeline", "deepsearch_scope", "update_checker_route", "stats", "provider_ledger_poller",
    "db_integrity_scheduler", "session_journal", "auto_sleep", "mcp_bridge_migration", "automations",
    "skill_auto_update", "mac_awake", "late_watches", "listing_push", "crosstalk_dispatcher", "messaging",
    "attention_watcher", "notify_sources", "core_services", "upload_sweeper", "server_log_rotate", "pipe_pruner",
    "skill_sweeper", "skill_journal_recovery", "work_backfill", "refresh_purge_loop", "refresh_store", "phone_link",
    "relay", "spectator_links_store", "browsers", "log_monitoring", "local_servers", "notifications",
    "engine_clients",
]

TEARDOWN_NAMES = [
    "request_log_rollup", "sidecar_runtime", "cplugs_host", "beast_lifecycle", "crosstalk_card_push",
    "computers_runtime", "pack_copy_sync", "peer_event_stream", "peer_links", "federation_listener",
    "federation_pair_socket", "federation_discovery", "update_checker", "lineage_live", "account_notice", "self_check",
    "transcript_manifest", "app_alerts", "pipeline", "deepsearch_index_scope", "update_checker_unset", "stats",
    "provider_ledger_poller", "db_integrity_scheduler", "session_journal_scheduler", "auto_sleep_task",
    "bridge_migration_task", "automation_scheduler", "catalog_index_refresher", "mac_awake_guard", "git_status_watch",
    "session_tasks_watch", "machine_stats_watch", "server_log_watch", "stats_feed", "resource_push",
    "listing_publisher_task", "crosstalk_dispatcher", "messaging_runtime", "attention_watcher_task",
    "attention_reader_state", "notify_sources", "remote_hosts", "upload_sweeper_task", "log_rotate_task",
    "pipe_pruner_task", "skill_sweeper_task", "skill_journal_task", "work_backfill_task", "refresh_purge_task",
    "refresh_store", "phone_link_boot", "spectator_relay", "spectator_links_store", "browser_sweep_task",
    "browser_manager", "log_monitor", "local_servers", "notifications", "control_input", "tmux_control_readers",
    "catalog_client",
]

STOP_RULES = {name: (False, ()) for name in STOP_ORDER}
STOP_RULES.update({
    "federation_link": (True, ()),
    "lineage_live": (True, ()),
    "provider_ledger_poller": (True, ()),
    "session_journal": (True, ()),
    "spectator_links_store": (False, ("spectator_relay",)),
})

DEGRADED = {
    "cli_command_shim": "cli_command_shim_write_failed",
    "first_run_import": "first_run_import_failed",
    "claude_hooks_strip": "claude_hooks_strip_failed",
    "provider_ledger_poller": "provider_ledger_poller_start_failed",
    "db_integrity_scheduler_start": "db_integrity_scheduler_start_failed",
    "session_journal": "session_journal_start_failed",
    "lineage_live": "lineage_live_start_failed",
    "federation_discovery": "federation_discovery_start_failed",
    "federation_link": "federation_link_start_failed",
}


def test_the_boot_starts_in_the_old_order() -> None:
    assert [step.name for step in build_registry().start_sequence()] == START_ORDER


def test_the_boot_stops_in_the_old_teardown_order() -> None:
    assert [step.name for step in build_registry().stop_sequence()] == STOP_ORDER


def test_only_the_old_guarded_steps_degrade_and_each_keeps_its_event() -> None:
    degraded = {s.name: s.failure_event for s in build_registry().start_sequence() if s.failure is FailureMode.DEGRADED}
    assert degraded == DEGRADED


def test_the_teardown_logs_under_the_2653_names_in_order() -> None:
    assert [name for step in build_registry().stop_sequence() for name in step.teardown_names] == TEARDOWN_NAMES


def test_each_stop_keeps_its_after_failure_and_requires_rules() -> None:
    rules = {s.name: (s.stop_after_failed_start, s.stop_requires) for s in build_registry().stop_sequence()}
    assert rules == STOP_RULES

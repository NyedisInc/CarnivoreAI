
from fastapi import APIRouter

from src.api import launch_profiles_routes
from src.api import ai_invoke_routes
from src.api import ai_routes
from src.api import notification_destinations_routes
from src.api import automation_attachment_routes, automation_command_routes, automation_log_routes, automation_routes, automation_run_routes
from src.api import notification_link_routes
from src.api import notification_presence_routes
from src.api import notification_test_routes
from src.api import notification_settings_routes
from src.api import notification_mute_routes
from src.api import cli_command_routes
from src.api import notification_sync_routes
from src.api import federation_notify_sync_routes
from src.api import federation_pack_replica_routes
from src.api import project_replica_routes, project_transport_routes
from src.api import notification_types_routes
from src.api import app_alerts_routes
from src.api import transcript_manifest_routes
from src.api import pipeline_plugin_routes
from src.api import self_check_routes
from src.api import search_index_routes
from src.api import browser_routes
from src.api import browser_open_routes
from src.api import open_files_routes
from src.api import ui_show_routes
from src.api import row_looks_routes
from src.api import filesystem_routes
from src.api import health_routes
from src.api import layout_skills_routes, layouts_routes
from src.api import blueprints_routes
from src.api import config_bundle_routes
from src.api import item_settings_routes
from src.api import board_routes
from src.api import crosstalk_routes
from src.api import agent_spawn_routes
from src.api import agent_fork_routes
from src.api import crosstalk_peer_routes
from src.api import dashboard_routes
from src.cplugs.host import routes as cplugs_host_routes
from src.api import (
    catalog_contents_routes,
    catalog_theme_palette_routes,
    catalog_required_routes,
    catalog_media_routes,
    catalog_hosted_routes,
    catalog_publish_routes,
    catalog_publish_author_routes,
    catalog_account_routes,
    catalog_community_routes,
    catalog_community_write_routes,
    catalog_email_signin_routes,
    catalog_google_signin_routes,
    catalog_web_signin_routes,
    catalog_note_routes,
    catalog_rating_routes,
    catalog_install_routes,
    catalog_install_report_routes,
    catalog_installed_routes,
    skill_card_art_routes,
    skills_census_routes,
    skill_md_edit_routes,
    skills_manager_routes,
    skills_command_routes,
    catalog_routes,
    one_shot_routes,
)
from src.api import projects_presence_routes
from src.api import projects_history_routes
from src.api import project_move_routes
from src.api import session_move_routes
from src.api import project_pack_routes
from src.api import companies_routes
from src.api import swarm_routes
from src.api import swarm_memory_routes
from src.api import swarm_card_routes
from src.api import swarm_node_order_routes
from src.api import swarm_switch_routes
from src.api import swarm_member_routes
from src.api import pack_machines_routes
from src.api import computers_routes
from src.api import pack_placement_routes
from src.api import federation_link_cert_routes, federation_pack_machine_routes, federation_pack_rollup_routes
from src.api import federation_pack_carry_routes, federation_pack_credentials_routes, federation_pack_gh_login_routes, federation_pack_migrate_routes, federation_pack_move_routes, federation_pack_skills_routes, federation_pack_span_routes, pack_skills_routes, federation_pack_transport_routes, pack_gh_login_routes, pack_migrate_routes, pack_move_routes, pack_ops_routes, pack_refresh_routes, pack_send_routes, pack_relay_consent_routes, pack_relay_routes
from src.api import hero_image_routes
from src.api import provider_account_removal_routes
from src.api import filesystem_peer_routes, launchers_peer_routes, provider_ledger_peer_routes, provider_ledger_routes
from src.api import features_routes
from src.api import whats_new_routes
from src.api import feature_media_routes
from src.api import agent_action_routes
from src.api import app_update_routes, app_update_peer_routes
from src.api import beast_mode_routes
from src.api import mcp_admin_routes
from src.api import api_keys_routes
from src.api import mcp_tool_routes
from src.api import auto_sleep_routes
from src.api import log_level_routes
from src.api import autonomy_routes, diagnostics_routes
from src.api import server_log_routes
from src.api import exports_routes
from src.api import machine_stats_routes
from src.api import provider_models_routes
from src.api import server_control_routes
from src.api import session_attach_command_routes
from src.api import session_attach_routes
from src.api import session_crud_routes
from src.api import companion_shell_routes
from src.api import session_conversations_routes
from src.api import session_prompt_texts_routes
from src.api import lineage_routes
from src.api import mcp_event_routes
from src.api import mcp_usage_routes
from src.api import session_contents_routes
from src.api import session_timeline_routes
from src.api import session_usage_routes
from src.api import session_companion_routes
from src.api import session_sleep_routes
from src.api import library_cleanup_routes
from src.api import session_discovery_routes
from src.api import session_fork_routes
from src.api import session_bookmark_routes
from src.api import session_import_status_routes
from src.api import session_input_routes
from src.api import session_upload_view_routes
from src.api import session_logs_routes
from src.api import session_recent_routes
from src.api import session_search_routes
from src.api import session_token_usage_routes
from src.api import subagent_routes
from src.api import session_skill_fires_routes
from src.api import skill_scout_routes
from src.api import skill_usage_routes
from src.api import skill_watch_routes
from src.api import session_timers_routes
from src.api import session_background_work_routes
from src.api import approvals_routes, session_dialog_routes
from src.api import web_push_routes
from src.api import native_device_routes
from src.api import mcp_reconnect_routes
from src.api import session_interrupt_routes
from src.api import scheduled_tasks_routes
from src.api import session_git_routes
from src.api import session_tasks_routes
from src.api import session_pane_facts_routes
from src.api import warroom_screen_routes
from src.api import session_records_routes
from src.api import session_purge_routes
from src.api import session_listing_push_routes
from src.api import session_rename_routes
from src.api import imported_restart_routes
from src.api import session_restart_apply_routes
from src.api import session_background_image_routes
from src.api import session_background_routes
from src.api import session_lease_routes
from src.api import session_notes_routes
from src.api import size_master_routes
from src.api import session_theme_routes
from src.api import spectator_routes
from src.api import session_toast_routes
from src.api import themes_routes
from src.api import theme_export_routes
from src.api import dev_shape_alerts_routes
from src.api import perf_routes
from src.api import agent_message_routes
from src.api import mods_routes
from src.api import messaging_agent_routes, messaging_routes
from src.api import descriptions_routes
from src.api import hosts_routes
from src.api import federation_discovery_routes, federation_peer_routes, federation_pending_routes, federation_routes
from src.core.version import freeze_startup_version

freeze_startup_version()

from src.api import stats_event_routes, stats_feed_routes, stats_insight_routes, stats_maintenance_routes, stats_routes, stats_tripwire_routes

router = APIRouter()
router.include_router(stats_routes.router)
router.include_router(stats_maintenance_routes.router)
router.include_router(stats_event_routes.router)
router.include_router(stats_tripwire_routes.router)
router.include_router(stats_insight_routes.router)
router.include_router(stats_feed_routes.router)
router.include_router(stats_feed_routes.peer_router)

router.include_router(session_discovery_routes.router)
router.include_router(provider_models_routes.local_models_router)
router.include_router(session_fork_routes.router)
router.include_router(session_bookmark_routes.router)
router.include_router(agent_fork_routes.router)
router.include_router(imported_restart_routes.router)
router.include_router(session_restart_apply_routes.router)
router.include_router(session_sleep_routes.router)
router.include_router(session_companion_routes.router)
router.include_router(session_conversations_routes.router)
router.include_router(session_prompt_texts_routes.router)
router.include_router(lineage_routes.router)
router.include_router(mcp_event_routes.router)
router.include_router(mcp_usage_routes.router)
router.include_router(session_timeline_routes.router)
router.include_router(session_contents_routes.router)
router.include_router(session_usage_routes.router)
router.include_router(library_cleanup_routes.router)
router.include_router(session_crud_routes.router)
router.include_router(companion_shell_routes.router)
router.include_router(session_attach_routes.router)
router.include_router(session_attach_command_routes.router)
router.include_router(session_background_routes.router)
router.include_router(session_background_image_routes.router)
router.include_router(session_theme_routes.router)
router.include_router(session_notes_routes.router)
router.include_router(session_lease_routes.router)
router.include_router(size_master_routes.router)
router.include_router(session_rename_routes.router)
router.include_router(session_input_routes.router)
router.include_router(session_upload_view_routes.router)
router.include_router(session_toast_routes.router)
router.include_router(session_logs_routes.router)
router.include_router(session_search_routes.router)
router.include_router(session_token_usage_routes.router)
router.include_router(subagent_routes.router)
router.include_router(session_timers_routes.router)
router.include_router(session_skill_fires_routes.router)
router.include_router(skill_usage_routes.router)
router.include_router(skill_watch_routes.router)
router.include_router(session_background_work_routes.router)
router.include_router(session_interrupt_routes.router)
router.include_router(mcp_reconnect_routes.router)
router.include_router(session_dialog_routes.router)
router.include_router(approvals_routes.router)
router.include_router(web_push_routes.router)
router.include_router(native_device_routes.router)
router.include_router(scheduled_tasks_routes.router)
router.include_router(session_pane_facts_routes.router)
router.include_router(warroom_screen_routes.router)
router.include_router(session_git_routes.router)
router.include_router(session_tasks_routes.router)
router.include_router(filesystem_routes.router)
router.include_router(provider_models_routes.router)
router.include_router(health_routes.router)
router.include_router(themes_routes.router)
router.include_router(theme_export_routes.router)
router.include_router(server_control_routes.router)
router.include_router(projects_presence_routes.router)
router.include_router(projects_history_routes.router)
router.include_router(project_move_routes.router)
router.include_router(session_move_routes.router)
router.include_router(project_pack_routes.router)
router.include_router(companies_routes.router)
router.include_router(swarm_routes.router)
router.include_router(swarm_memory_routes.router)
router.include_router(swarm_member_routes.router)
router.include_router(swarm_card_routes.router)
router.include_router(swarm_node_order_routes.router)
router.include_router(swarm_switch_routes.router)
router.include_router(pack_machines_routes.router)
router.include_router(pack_skills_routes.router)
router.include_router(computers_routes.router)
router.include_router(pack_placement_routes.router)
router.include_router(federation_link_cert_routes.router)
router.include_router(federation_pack_machine_routes.router)
router.include_router(federation_pack_rollup_routes.router)
router.include_router(pack_relay_consent_routes.router)
router.include_router(pack_relay_routes.router)
router.include_router(federation_pack_credentials_routes.router)
router.include_router(pack_gh_login_routes.router)
router.include_router(federation_pack_gh_login_routes.router)
router.include_router(federation_pack_span_routes.router)
router.include_router(pack_refresh_routes.router)
router.include_router(federation_pack_transport_routes.router)
router.include_router(federation_pack_skills_routes.router)
router.include_router(pack_migrate_routes.router)
router.include_router(federation_pack_migrate_routes.router)
router.include_router(pack_move_routes.router)
router.include_router(pack_ops_routes.router)
router.include_router(pack_send_routes.router)
router.include_router(federation_pack_move_routes.router)
router.include_router(federation_pack_carry_routes.router)
router.include_router(hero_image_routes.router)
router.include_router(session_records_routes.router)
router.include_router(session_purge_routes.router)
router.include_router(session_listing_push_routes.router)
router.include_router(session_recent_routes.router)
router.include_router(session_import_status_routes.router)
router.include_router(one_shot_routes.router)
router.include_router(skill_scout_routes.router)
router.include_router(catalog_hosted_routes.router)
router.include_router(catalog_contents_routes.router)
router.include_router(catalog_theme_palette_routes.router)
router.include_router(catalog_required_routes.router)
router.include_router(catalog_media_routes.router)
router.include_router(catalog_rating_routes.router)
router.include_router(catalog_note_routes.router)
router.include_router(catalog_publish_routes.router)
router.include_router(catalog_publish_author_routes.router)
router.include_router(catalog_email_signin_routes.router)
router.include_router(catalog_google_signin_routes.router)
router.include_router(catalog_web_signin_routes.router)
router.include_router(catalog_account_routes.router)
router.include_router(catalog_community_routes.router)
router.include_router(catalog_community_write_routes.router)
router.include_router(catalog_routes.router)
router.include_router(catalog_install_routes.router)
router.include_router(catalog_installed_routes.router)
router.include_router(catalog_install_report_routes.router)
router.include_router(skills_manager_routes.router)
router.include_router(skill_card_art_routes.router)
router.include_router(skill_md_edit_routes.router)
router.include_router(skills_command_routes.router)
router.include_router(skills_census_routes.router)
router.include_router(provider_account_removal_routes.router)
router.include_router(provider_ledger_routes.router)
router.include_router(provider_ledger_peer_routes.router)
router.include_router(launchers_peer_routes.router)
router.include_router(filesystem_peer_routes.router)
router.include_router(spectator_routes.router)
router.include_router(browser_routes.router)
router.include_router(browser_open_routes.router)
router.include_router(open_files_routes.router)
router.include_router(row_looks_routes.router)
router.include_router(auto_sleep_routes.router)
router.include_router(log_level_routes.router)
router.include_router(autonomy_routes.router)
router.include_router(diagnostics_routes.router)
router.include_router(server_log_routes.router)
router.include_router(exports_routes.router)
router.include_router(machine_stats_routes.router)
router.include_router(agent_action_routes.router)
router.include_router(beast_mode_routes.router)
router.include_router(app_update_routes.router)
router.include_router(app_update_peer_routes.served)
router.include_router(app_update_peer_routes.asked)
router.include_router(mcp_admin_routes.router)
router.include_router(api_keys_routes.router)
router.include_router(mcp_tool_routes.router)
router.include_router(layouts_routes.router)
router.include_router(layout_skills_routes.router)
router.include_router(blueprints_routes.router)
router.include_router(features_routes.router)
router.include_router(whats_new_routes.router)
router.include_router(feature_media_routes.router)
router.include_router(item_settings_routes.router)
router.include_router(board_routes.router)
router.include_router(crosstalk_routes.router)
router.include_router(agent_spawn_routes.router)
router.include_router(crosstalk_peer_routes.router)
router.include_router(dashboard_routes.router)
router.include_router(cplugs_host_routes.router)
router.include_router(config_bundle_routes.router)
router.include_router(launch_profiles_routes.router)
router.include_router(dev_shape_alerts_routes.router)
router.include_router(perf_routes.router)
router.include_router(app_alerts_routes.router)
router.include_router(self_check_routes.router)
router.include_router(transcript_manifest_routes.router)
router.include_router(pipeline_plugin_routes.router)
router.include_router(search_index_routes.router)
router.include_router(hosts_routes.router)
router.include_router(federation_discovery_routes.router)
router.include_router(federation_routes.router)
router.include_router(federation_pending_routes.router)
router.include_router(federation_peer_routes.router)
router.include_router(notification_link_routes.router)
router.include_router(notification_presence_routes.router)
router.include_router(notification_test_routes.router)
router.include_router(ai_routes.router)
router.include_router(ai_invoke_routes.router)
router.include_router(notification_types_routes.router)
router.include_router(notification_settings_routes.router)
router.include_router(notification_mute_routes.router)
router.include_router(cli_command_routes.router)
router.include_router(notification_destinations_routes.router)
router.include_router(automation_routes.router)
router.include_router(automation_log_routes.router)
router.include_router(automation_command_routes.router)
router.include_router(automation_run_routes.router)
router.include_router(automation_attachment_routes.router)
router.include_router(notification_sync_routes.router)
router.include_router(federation_notify_sync_routes.router)
router.include_router(federation_pack_replica_routes.router)
router.include_router(project_replica_routes.router)
router.include_router(project_transport_routes.router)
router.include_router(agent_message_routes.router)
router.include_router(mods_routes.router)
router.include_router(messaging_routes.router)
router.include_router(messaging_agent_routes.router)
router.include_router(descriptions_routes.router)
from src.api import deepsearch_peer_routes, deepsearch_routes
router.include_router(deepsearch_peer_routes.router)
router.include_router(deepsearch_routes.router)
router.include_router(ui_show_routes.router)

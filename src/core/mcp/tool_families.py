
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.cplugs.sdk.tool_families import TASK_MANAGER_PREFIX

SWITCH, AUTOMATIC = "switch", "automatic"


@dataclass(frozen=True)
class Family:

    key: str
    label: str
    kind: str
    why: str
    how: str
    prefixes: tuple[str, ...] = ()
    names: frozenset[str] = frozenset()
    excludes: frozenset[str] = frozenset()

    def has(self, name: str) -> bool:
        return name not in self.excludes and (name in self.names or name.startswith(self.prefixes))


_PACK = frozenset({
    "pack_gh_login_add", "pack_machines_list", "pack_master_set", "pack_op_get", "pack_queue_cancel", "pack_queue_items_list",
    "pack_refresh_run", "pack_relay_set", "pack_relay_status", "pack_reserve_get", "pack_skills_status", "pack_reserve_set", "pack_restrictions_get",
    "pack_restrictions_set", "pack_settings_update", "pack_tracks_master_get", "pack_tracks_master_set", "placement_explain",
    "project_replica_list", "project_replica_add", "project_replica_remove", "project_sync", "project_migrate",
    "project_migrate_back", "project_migrate_plan", "company_migrate", "company_migrate_plan", "session_move", "session_send",
    "session_send_check", "computer_direction_set", "computer_leave", "computer_remove",
})

_MESSAGING = frozenset({
    "messaging_conversations_list", "messaging_bindings_list", "messaging_conversation_add", "messaging_binding_create",
    "messaging_binding_delete", "messaging_send",
})

_AI = frozenset({"ai_models_list", "ai_features_list", "ai_calls_list"})

_APP_SETTINGS = frozenset({
    "session_pins_list", "session_pin", "session_unpin", "session_groups_list", "session_group_create", "session_group_move",
    "session_group_rename", "session_group_delete", "session_group_color_set", "preferences_get",
    "preferences_update", "layout_color_set", "skills_command_center", "skill_copy", "skill_remove", "mods_list",
    "mod_enabled_set", "mod_remove", "catalog_items_list", "pipeline_plugin_rebuild", "alert_open_system_settings",
})

SWARM_SWITCH_TOOLS = frozenset({"swarm_switch_status", "swarm_switch_off", "swarm_switch_on"})

_PANEL = "settings > sessions & agents > mcp server"
_RESTART = "A Codex or plain-HTTP pane needs a restart or /mcp reconnect to see the change."

FAMILIES: tuple[Family, ...] = (
    Family(
        key="huddle", label="huddle tools", kind=SWITCH,
        prefixes=("huddle_", TASK_MANAGER_PREFIX),
        why="the owner turned huddle tools off for agents on this computer",
        how=f"The owner turns them on in {_PANEL}."),
    Family(
        key="swarm", label="swarm tools", kind=SWITCH, prefixes=("swarm_",), excludes=SWARM_SWITCH_TOOLS,
        why="the owner turned swarm tools off for agents on this computer",
        how=f"The owner turns them on in {_PANEL}."),
    Family(
        key="pack", label="pack tools", kind=AUTOMATIC, names=_PACK,
        why="no other computer is linked to this one, and there is no project replica, queued placement or open migration",
        how=f"Pair a computer with computer_add (computer_add_preview shows what it will do first); these tools unlock after the join completes. {_RESTART}"),
    Family(
        key="messaging", label="messaging tools", kind=AUTOMATIC, names=_MESSAGING,
        why="no messaging provider is connected",
        how=f"The owner connects a provider in the app (settings > notifications > messaging); these tools unlock then. {_RESTART}"),
    Family(
        key="ai", label="ai tools", kind=AUTOMATIC, names=_AI,
        why="no AI connection is saved",
        how=f"Save a connection in the app's ai settings (ai_connections_list shows them); these tools unlock then. {_RESTART}"),
    Family(
        key="app_settings", label="app settings tools", kind=SWITCH, names=_APP_SETTINGS,
        why="the owner keeps the app's own settings off limits to agents on this computer",
        how=f"The owner ticks app settings tools in {_PANEL}."),
)

BY_KEY = {f.key: f for f in FAMILIES}


def family_of(name: str) -> Optional[Family]:
    return next((f for f in FAMILIES if f.has(name)), None)

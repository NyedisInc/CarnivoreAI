
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, field_validator

from src.core.attention.kinds_choice import AttentionKindsChoice
from src.core.widget_placement.widget_bars import WidgetBars
from src.core.ui_preferences.drawer_arrangement import DrawerArrangement
from src.core.ui_preferences.drawer_row_icons import DrawerRowIcons
from src.core.ui_preferences.drawer_zone import DrawerZone, SessionRail
from src.core.ui_preferences.account_checks import check_builtin_login_label, check_owner_display_name, check_account_welcome_seen, check_time_zone
from src.core.ui_preferences.activity_checks import check_toast_mode, check_terminal_screen_reader, check_deepsearch_index_scope, check_swarm_chat_muted, check_automation_runs_seen_at, check_warez_last_call, check_automation_runs_read, check_disabled_plugin_ids, check_terminal_layouts_size, check_home_layout_size
from src.core.ui_preferences.keymap_checks import check_keymap
from src.core.ui_preferences.desktop_checks import check_desktop_bools, check_desktop_hotkey, check_desktop_terminal_app, check_desktop_terminal_custom
from src.core.ui_preferences.sidebar_checks import check_menu_order, check_rail_hidden_icons, check_density, check_rail_magnify, check_sidebar_layout, check_widget_drawer_view, check_sidebar_tab_colors, check_drawer_arrangement_size, check_collapsed_paths, check_launchpad_sections, check_foot_bar_items, check_foot_bar_order
from src.core.ui_preferences.theme_checks import check_theme_id, check_favorite_theme_ids, check_script_consent, check_model_id, check_favorite_skill_names
from src.core.ui_preferences.layouts import FootBarLayout, HomeLayout, TerminalLayouts, WarroomLayout



class UiPreferenceValues(BaseModel):
    """Every preference this server understands, all of them optional.

    ABSENT IS NOT A DEFAULT. Every field defaults to ``None``, meaning
    "the user has never set this here", and the client keeps using its
    own default. The server never fabricates a value, so hydrating from
    an empty block can never overwrite a real local setting with a
    server-side guess - which is the failure #44 names as one of the two
    that silently corrupt settings.
    """

    model_config = ConfigDict(extra="forbid")

    theme: Optional[str] = None
    launch_last_model: Optional[str] = None
    sidebar_density: Optional[str] = None
    sidebar_density_mobile: Optional[str] = None
    widget_drawer_view: Optional[str] = None
    widget_drawer_view_mobile: Optional[str] = None
    sidebar_show_leaders: Optional[StrictBool] = None
    sidebar_show_archived: Optional[StrictBool] = None
    sidebar_show_stats: Optional[StrictBool] = None
    sidebar_show_stats_mobile: Optional[StrictBool] = None
    sidebar_layout: Optional[str] = None
    sidebar_show_closed: Optional[StrictBool] = None
    sidebar_show_closed_mobile: Optional[StrictBool] = None
    sidebar_list_open: Optional[StrictBool] = None
    sidebar_list_open_mobile: Optional[StrictBool] = None
    sidebar_list_sleeping: Optional[StrictBool] = None
    sidebar_list_sleeping_mobile: Optional[StrictBool] = None
    sidebar_hide_empty_sections: Optional[StrictBool] = None
    menu_order: Optional[List[str]] = None
    rail_hidden_icons: Optional[List[str]] = None
    sidebar_pinned: Optional[bool] = None
    config_editor_collapsed: Optional[Dict[str, bool]] = None
    launchpad_collapsed: Optional[Dict[str, bool]] = None
    theme_script_consent: Optional[Dict[str, Any]] = None
    theme_favorites: Optional[List[str]] = None
    skill_favorites: Optional[List[str]] = None
    terminal_layouts: Optional[TerminalLayouts] = None
    drawer_arrangement: Optional[DrawerArrangement] = None
    home_layout: Optional[HomeLayout] = None
    warroom_layout: Optional[WarroomLayout] = None
    drawer_zone: Optional[DrawerZone] = None
    session_rail: Optional[SessionRail] = None
    session_rail_bottom: Optional[SessionRail] = None
    widget_bars: Optional[WidgetBars] = None
    automation_runs_seen_at: Optional[str] = None
    automation_runs_read: Optional[List[str]] = None
    warez_last_call: Optional[str] = None
    warez_elite_seen: Optional[StrictBool] = None
    waiting_kinds: Optional[AttentionKindsChoice] = None
    animations: Optional[StrictBool] = None
    row_lights_animate: Optional[StrictBool] = None
    rail_magnify: Optional[StrictInt] = None
    rail_dock_names: Optional[StrictBool] = None
    notify_quiet_watched: Optional[StrictBool] = None
    disabled_plugins: Optional[List[str]] = None
    toast_mode: Optional[str] = None
    terminal_screen_reader: Optional[str] = None
    crosstalk_cards: Optional[StrictBool] = None
    crosstalk_card_sender: Optional[StrictBool] = None
    crosstalk_card_receiver: Optional[StrictBool] = None
    crosstalk_card_keep: Optional[StrictBool] = None
    deepsearch_index_scope: Optional[str] = None
    drawer_row_icons: Optional[DrawerRowIcons] = None
    sidebar_tab_colors: Optional[Dict[str, str]] = None
    builtin_login_label: Optional[str] = None
    owner_display_name: Optional[str] = None
    time_zone: Optional[str] = None
    desktop_banners: Optional[bool] = None
    desktop_banner_hide_command: Optional[bool] = None
    desktop_notify_asks_only: Optional[bool] = None
    desktop_hotkey: Optional[str] = None
    mac_option_is_meta: Optional[bool] = None
    desktop_menu_bar_icon: Optional[bool] = None
    desktop_terminal_app: Optional[str] = None
    desktop_terminal_custom: Optional[str] = None
    account_welcome_seen: Optional[bool] = None
    foot_bar_items: Optional[Dict[str, StrictBool]] = None
    foot_bar_layout: Optional[FootBarLayout] = None
    foot_bar_order: Optional[List[str]] = None
    swarm_chat_muted: Optional[List[str]] = None
    keymap: Optional[Dict[str, Dict[str, List[str]]]] = None

    _menu_order = field_validator("menu_order")(check_menu_order)
    _rail_hidden_icons = field_validator("rail_hidden_icons")(check_rail_hidden_icons)
    _density = field_validator("sidebar_density", "sidebar_density_mobile")(check_density)
    _sidebar_layout = field_validator("sidebar_layout")(check_sidebar_layout)
    _rail_magnify = field_validator("rail_magnify")(check_rail_magnify)
    _widget_drawer_view = field_validator("widget_drawer_view", "widget_drawer_view_mobile")(check_widget_drawer_view)
    _sidebar_tab_colors = field_validator("sidebar_tab_colors")(check_sidebar_tab_colors)
    _drawer_arrangement_size = field_validator("drawer_arrangement")(check_drawer_arrangement_size)
    _collapsed_paths = field_validator("config_editor_collapsed")(check_collapsed_paths)
    _launchpad_sections = field_validator("launchpad_collapsed")(check_launchpad_sections)
    _foot_bar_items = field_validator("foot_bar_items")(check_foot_bar_items)
    _foot_bar_order = field_validator("foot_bar_order")(check_foot_bar_order)
    _theme_id = field_validator("theme")(check_theme_id)
    _favorite_theme_ids = field_validator("theme_favorites")(check_favorite_theme_ids)
    _script_consent = field_validator("theme_script_consent")(check_script_consent)
    _model_id = field_validator("launch_last_model")(check_model_id)
    _favorite_skill_names = field_validator("skill_favorites")(check_favorite_skill_names)
    _desktop_bools = field_validator("desktop_banners", "desktop_banner_hide_command", "desktop_notify_asks_only", "mac_option_is_meta", "desktop_menu_bar_icon", mode="before")(check_desktop_bools)
    _desktop_hotkey = field_validator("desktop_hotkey", mode="before")(check_desktop_hotkey)
    _desktop_terminal_app = field_validator("desktop_terminal_app", mode="before")(check_desktop_terminal_app)
    _desktop_terminal_custom = field_validator("desktop_terminal_custom", mode="before")(check_desktop_terminal_custom)
    _builtin_login_label = field_validator("builtin_login_label")(check_builtin_login_label)
    _owner_display_name = field_validator("owner_display_name")(check_owner_display_name)
    _account_welcome_seen = field_validator("account_welcome_seen", mode="before")(check_account_welcome_seen)
    _time_zone = field_validator("time_zone")(check_time_zone)
    _toast_mode = field_validator("toast_mode")(check_toast_mode)
    _terminal_screen_reader = field_validator("terminal_screen_reader")(check_terminal_screen_reader)
    _deepsearch_index_scope = field_validator("deepsearch_index_scope")(check_deepsearch_index_scope)
    _swarm_chat_muted = field_validator("swarm_chat_muted")(check_swarm_chat_muted)
    _keymap = field_validator("keymap")(check_keymap)
    _automation_runs_seen_at = field_validator("automation_runs_seen_at")(check_automation_runs_seen_at)
    _warez_last_call = field_validator("warez_last_call")(check_warez_last_call)
    _automation_runs_read = field_validator("automation_runs_read")(check_automation_runs_read)
    _disabled_plugin_ids = field_validator("disabled_plugins")(check_disabled_plugin_ids)
    _terminal_layouts_size = field_validator("terminal_layouts")(check_terminal_layouts_size)
    _home_layout_size = field_validator("home_layout")(check_home_layout_size)

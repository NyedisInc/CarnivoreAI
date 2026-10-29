
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationInfo, field_validator

from src.core import theme_script_consent
from src.core.desktop_app import preferences as desktop_preferences
from src.core.time_zone import app_time_zone
from src.core.automations.ui_prefs import check_read_run_ids, check_seen_at
from src.core.attention.kinds_choice import AttentionKindsChoice
from src.core.widget_placement.widget_bars import WidgetBars
from src.cplugs.sdk import chat_category
from src.core.ui_preferences.constants import BUILTIN_LOGIN_LABEL_MAX, DEEPSEARCH_INDEX_SCOPES, FOOT_BAR_ITEM_IDS, FOOT_BAR_ORDER_IDS, LAUNCHPAD_SECTION_IDS, MAX_COLLAPSED_PATHS, MAX_DISABLED_PLUGINS, MAX_HOME_LAYOUT_BYTES, MAX_KEY_LENGTH, MAX_MENU_ORDER, MAX_SIDEBAR_TAB_COLORS, MAX_SKILL_FAVORITES, MAX_SKILL_NAME_CHARS, MAX_TERMINAL_LAYOUTS_BYTES, MAX_THEME_FAVORITES, MODEL_ID_RE, OWNER_DISPLAY_NAME_MAX, SIDEBAR_DENSITIES, SIDEBAR_LAYOUTS, SIDEBAR_TAB_COLOR_NAMES, SIDEBAR_TAB_ID_RE, TERMINAL_SCREEN_READER_MODES, THEME_ID_RE, TOAST_MODES, WIDGET_DRAWER_VIEWS
from src.core.ui_preferences.drawer import DrawerArrangement, DrawerRowIcons, DrawerZone, MAX_DRAWER_ARRANGEMENT_BYTES, SessionRail
from src.core.ui_preferences.layouts import FootBarLayout, HomeLayout, TerminalLayouts, WarroomLayout
from src.core.ui_preferences.checks import json_size_cap


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

    @field_validator("swarm_chat_muted")
    @classmethod
    def _swarm_chat_muted(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return chat_category.check_muted(value)

    @field_validator("automation_runs_seen_at")
    @classmethod
    def _automation_runs_seen_at(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else check_seen_at(value)

    @field_validator("warez_last_call")
    @classmethod
    def _warez_last_call(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else check_seen_at(value)

    @field_validator("automation_runs_read")
    @classmethod
    def _automation_runs_read(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return None if value is None else check_read_run_ids(value)

    @field_validator("toast_mode")
    @classmethod
    def _toast_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in TOAST_MODES:
            raise ValueError(f"toast_mode must be one of {list(TOAST_MODES)}")
        return value

    @field_validator("terminal_screen_reader")
    @classmethod
    def _terminal_screen_reader(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in TERMINAL_SCREEN_READER_MODES:
            raise ValueError(f"terminal_screen_reader must be one of {list(TERMINAL_SCREEN_READER_MODES)}")
        return value

    @field_validator("deepsearch_index_scope")
    @classmethod
    def _deepsearch_index_scope(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in DEEPSEARCH_INDEX_SCOPES:
            raise ValueError(f"deepsearch_index_scope must be one of {list(DEEPSEARCH_INDEX_SCOPES)}")
        return value

    @field_validator("foot_bar_items")
    @classmethod
    def _foot_bar_items(cls, value: Optional[Dict[str, bool]]) -> Optional[Dict[str, bool]]:
        if value is None:
            return None
        for key in value:
            if key not in FOOT_BAR_ITEM_IDS:
                raise ValueError(f"foot_bar_items only covers {list(FOOT_BAR_ITEM_IDS)}")
        return value

    @field_validator("foot_bar_order")
    @classmethod
    def _foot_bar_order(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        if sorted(value) != sorted(FOOT_BAR_ORDER_IDS):
            raise ValueError(f"foot_bar_order must name each of {list(FOOT_BAR_ORDER_IDS)} exactly once")
        return list(value)

    @field_validator("disabled_plugins")
    @classmethod
    def _disabled_plugin_ids(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        return list(dict.fromkeys(i for i in value if isinstance(i, str)))[:MAX_DISABLED_PLUGINS]

    @field_validator("menu_order")
    @classmethod
    def _menu_order(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        if any(not isinstance(i, str) or not i or len(i) > MAX_KEY_LENGTH for i in value):
            raise ValueError("menu_order holds destination ids (non-empty strings)")
        out = list(dict.fromkeys(value))
        if len(out) > MAX_MENU_ORDER:
            raise ValueError(f"at most {MAX_MENU_ORDER} menu rows")
        return out

    @field_validator("rail_hidden_icons")
    @classmethod
    def _rail_hidden_icons(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        if any(not isinstance(i, str) or not i or len(i) > MAX_KEY_LENGTH for i in value):
            raise ValueError("rail_hidden_icons holds icon ids (non-empty strings)")
        out = list(dict.fromkeys(value))
        if len(out) > MAX_MENU_ORDER:
            raise ValueError(f"at most {MAX_MENU_ORDER} rail icons")
        return out

    @field_validator("drawer_arrangement")
    @classmethod
    def _drawer_arrangement_size(cls, value: Optional[DrawerArrangement]) -> Optional[DrawerArrangement]:
        if value is None:
            return None
        json_size_cap(value.model_dump(mode="json"), MAX_DRAWER_ARRANGEMENT_BYTES, "drawer_arrangement is too large to store")
        return value

    @field_validator("terminal_layouts")
    @classmethod
    def _terminal_layouts_size(cls, value: Optional[TerminalLayouts]) -> Optional[TerminalLayouts]:
        if value is None:
            return None
        json_size_cap(value.model_dump(mode="json"), MAX_TERMINAL_LAYOUTS_BYTES, "terminal_layouts is too large to store")
        return value

    @field_validator("home_layout")
    @classmethod
    def _home_layout_size(cls, value: Optional[HomeLayout]) -> Optional[HomeLayout]:
        if value is None:
            return None
        json_size_cap(value.model_dump(mode="json"), MAX_HOME_LAYOUT_BYTES, "home_layout is too large to store")
        return value

    @field_validator("theme")
    @classmethod
    def _theme_id(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not THEME_ID_RE.match(value):
            raise ValueError("theme must be a theme id like 'claude' or 'matrix'")
        return value

    @field_validator("theme_favorites")
    @classmethod
    def _favorite_theme_ids(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        if len(value) > MAX_THEME_FAVORITES:
            raise ValueError(f"at most {MAX_THEME_FAVORITES} favorite themes")
        for theme_id in value:
            if not THEME_ID_RE.match(theme_id):
                raise ValueError("theme_favorites holds theme ids like 'claude' or 'matrix'")
        return list(dict.fromkeys(value))

    @field_validator("skill_favorites")
    @classmethod
    def _favorite_skill_names(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        if len(value) > MAX_SKILL_FAVORITES:
            raise ValueError(f"at most {MAX_SKILL_FAVORITES} favorite skills")
        for name in value:
            if not name.strip() or len(name) > MAX_SKILL_NAME_CHARS or any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
                raise ValueError("skill_favorites holds skill names: non-empty, no control characters, at most 200 characters")
        return list(dict.fromkeys(value))

    @field_validator("launch_last_model")
    @classmethod
    def _model_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == "":
            return value
        if not MODEL_ID_RE.match(value):
            raise ValueError("launch_last_model is not a valid model id")
        return value

    @field_validator("sidebar_tab_colors")
    @classmethod
    def _sidebar_tab_colors(cls, value: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        if value is None:
            return None
        if len(value) > MAX_SIDEBAR_TAB_COLORS:
            raise ValueError(f"sidebar_tab_colors holds at most {MAX_SIDEBAR_TAB_COLORS} tabs")
        for tab_id, color in value.items():
            if not SIDEBAR_TAB_ID_RE.match(tab_id):
                raise ValueError("sidebar_tab_colors is keyed by tab ids like 'agents'")
            if color not in SIDEBAR_TAB_COLOR_NAMES:
                raise ValueError(
                    "sidebar_tab_colors takes a theme colour name: "
                    + ", ".join(SIDEBAR_TAB_COLOR_NAMES)
                )
        return dict(value)

    @field_validator("builtin_login_label")
    @classmethod
    def _builtin_login_label(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        label = value.strip()
        if not label or len(label) > BUILTIN_LOGIN_LABEL_MAX:
            raise ValueError(
                f"builtin_login_label must be 1 to {BUILTIN_LOGIN_LABEL_MAX} characters"
            )
        if any(not ch.isprintable() for ch in label):
            raise ValueError("builtin_login_label must not contain control characters")
        return label

    @field_validator("account_welcome_seen", mode="before")
    @classmethod
    def _account_welcome_seen(cls, value: Any) -> Optional[bool]:
        if value is not None and not isinstance(value, bool):
            raise ValueError("account_welcome_seen must be a boolean")
        return value

    @field_validator("time_zone")
    @classmethod
    def _time_zone(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else app_time_zone.validate(value)

    @field_validator("desktop_banners", "desktop_banner_hide_command", "desktop_notify_asks_only", "mac_option_is_meta", "desktop_menu_bar_icon", mode="before")
    @classmethod
    def _desktop_bools(cls, value: Any, info: ValidationInfo) -> Optional[bool]:
        return None if value is None else desktop_preferences.validate_bool(info.field_name, value)

    @field_validator("desktop_hotkey", mode="before")
    @classmethod
    def _desktop_hotkey(cls, value: Any) -> Optional[str]:
        return None if value is None else desktop_preferences.validate_hotkey(value)

    @field_validator("desktop_terminal_app", mode="before")
    @classmethod
    def _desktop_terminal_app(cls, value: Any) -> Optional[str]:
        return None if value is None else desktop_preferences.validate_terminal_app(value)

    @field_validator("desktop_terminal_custom", mode="before")
    @classmethod
    def _desktop_terminal_custom(cls, value: Any) -> Optional[str]:
        return None if value is None else desktop_preferences.validate_terminal_custom(value)

    @field_validator("owner_display_name")
    @classmethod
    def _owner_display_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        name = value.strip()
        if not name or len(name) > OWNER_DISPLAY_NAME_MAX:
            raise ValueError(
                f"owner_display_name must be 1 to {OWNER_DISPLAY_NAME_MAX} characters"
            )
        if any(not ch.isprintable() for ch in name):
            raise ValueError("owner_display_name must not contain control characters")
        return name

    @field_validator("sidebar_density", "sidebar_density_mobile")
    @classmethod
    def _density(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        if value is not None and value not in SIDEBAR_DENSITIES:
            raise ValueError(f"{info.field_name} must be one of {list(SIDEBAR_DENSITIES)}")
        return value

    @field_validator("sidebar_layout")
    @classmethod
    def _sidebar_layout(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        if value is not None and value not in SIDEBAR_LAYOUTS:
            raise ValueError(f"{info.field_name} must be one of {list(SIDEBAR_LAYOUTS)}")
        return value

    @field_validator("widget_drawer_view", "widget_drawer_view_mobile")
    @classmethod
    def _widget_drawer_view(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        if value is not None and value not in WIDGET_DRAWER_VIEWS:
            raise ValueError(f"{info.field_name} must be one of {list(WIDGET_DRAWER_VIEWS)}")
        return value

    @field_validator("config_editor_collapsed")
    @classmethod
    def _collapsed_paths(cls, value: Optional[Dict[str, bool]]) -> Optional[Dict[str, bool]]:
        if value is None:
            return None
        if len(value) > MAX_COLLAPSED_PATHS:
            raise ValueError(f"at most {MAX_COLLAPSED_PATHS} remembered tree nodes")
        for key in value:
            if not key or len(key) > MAX_KEY_LENGTH * 8:
                raise ValueError("a tree node key must be 1 to 1024 characters")
        return value

    @field_validator("launchpad_collapsed")
    @classmethod
    def _launchpad_sections(cls, value: Optional[Dict[str, bool]]) -> Optional[Dict[str, bool]]:
        if value is None:
            return None
        for key in value:
            if key not in LAUNCHPAD_SECTION_IDS:
                raise ValueError(
                    f"launchpad_collapsed only covers {list(LAUNCHPAD_SECTION_IDS)}"
                )
        return value

    @field_validator("theme_script_consent")
    @classmethod
    def _script_consent(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        return theme_script_consent.validate_consent_map(value)

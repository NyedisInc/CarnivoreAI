
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from pydantic import ValidationInfo

from src.core.time_zone import app_time_zone
from src.core.ui_preferences.checks import json_size_cap
from src.core.ui_preferences.constants import (
    FILTER_KEY_RE,
    FOOT_BAR_ITEM_IDS,
    FOOT_BAR_ORDER_IDS,
    LAUNCHPAD_SECTION_IDS,
    LAYOUT_TAB_ID_RE,
    MAX_ANALYTICS_FILTER_KEYS,
    MAX_ANALYTICS_FILTERS_BYTES,
    MAX_ANALYTICS_TIMEZONE_CHARS,
    MAX_COLLAPSED_PATHS,
    MAX_KEY_LENGTH,
    MAX_LAYOUT_TABS,
    MAX_MENU_ORDER,
    MAX_SIDEBAR_TAB_COLORS,
    MAX_TIMELINE_FILTER_KEYS,
    MAX_TIMELINE_FILTERS_BYTES,
    MAX_WIDGET_STATE_ENTRIES,
    MAX_WIDGET_STATE_ENTRY_BYTES,
    MENU_PAGE_WIDTH_MAX_PX,
    MENU_PAGE_WIDTH_MIN_PX,
    RAIL_MAGNIFY_PERCENTS,
    SIDEBAR_DENSITIES,
    SIDEBAR_LAYOUTS,
    SIDEBAR_TAB_COLOR_NAMES,
    SIDEBAR_TAB_ID_RE,
    STATS_BAR_RATES,
    STATS_BAR_WINDOWS,
    WIDGET_DRAWER_VIEWS,
    WIDGET_STATE_ID_RE,
)
from src.core.ui_preferences.drawer_arrangement import DrawerArrangement, MAX_DRAWER_ARRANGEMENT_BYTES

_SECRET_SUBKEY_RE = re.compile(
    r"(token|secret|password|passphrase|api[_-]?key|cookie|credential|private[_-]?key|access[_-]?key|bearer|jwt|(?:^|[_.-])auth(?:$|[_.-]))",
    re.I,
)
_MAX_PREF_JSON_DEPTH = 8


class SidebarChecksError(ValueError):
    pass


def check_menu_order(value: Optional[List[str]]) -> Optional[List[str]]:
    if value is None:
        return None
    if any(not isinstance(i, str) or not i or len(i) > MAX_KEY_LENGTH for i in value):
        raise ValueError("menu_order holds destination ids (non-empty strings)")
    out = list(dict.fromkeys(value))
    if len(out) > MAX_MENU_ORDER:
        raise ValueError(f"at most {MAX_MENU_ORDER} menu rows")
    return out


def check_rail_hidden_icons(value: Optional[List[str]]) -> Optional[List[str]]:
    if value is None:
        return None
    if any(not isinstance(i, str) or not i or len(i) > MAX_KEY_LENGTH for i in value):
        raise ValueError("rail_hidden_icons holds icon ids (non-empty strings)")
    out = list(dict.fromkeys(value))
    if len(out) > MAX_MENU_ORDER:
        raise ValueError(f"at most {MAX_MENU_ORDER} rail icons")
    return out


def check_density(value: Optional[str], info: ValidationInfo) -> Optional[str]:
    if value is not None and value not in SIDEBAR_DENSITIES:
        raise ValueError(f"{info.field_name} must be one of {list(SIDEBAR_DENSITIES)}")
    return value


def check_rail_magnify(value: Optional[int]) -> Optional[int]:
    if value is not None and value not in RAIL_MAGNIFY_PERCENTS:
        raise ValueError(f"rail_magnify must be one of {list(RAIL_MAGNIFY_PERCENTS)}")
    return value


def check_menu_page_width(value: Optional[int]) -> Optional[int]:
    if value is not None and not MENU_PAGE_WIDTH_MIN_PX <= value <= MENU_PAGE_WIDTH_MAX_PX:
        raise ValueError(f"menu_page_width must be {MENU_PAGE_WIDTH_MIN_PX} to {MENU_PAGE_WIDTH_MAX_PX} px")
    return value


def check_sidebar_layout(value: Optional[str], info: ValidationInfo) -> Optional[str]:
    if value is not None and value not in SIDEBAR_LAYOUTS:
        raise ValueError(f"{info.field_name} must be one of {list(SIDEBAR_LAYOUTS)}")
    return value


def check_widget_drawer_view(value: Optional[str], info: ValidationInfo) -> Optional[str]:
    if value is not None and value not in WIDGET_DRAWER_VIEWS:
        raise ValueError(f"{info.field_name} must be one of {list(WIDGET_DRAWER_VIEWS)}")
    return value


def check_sidebar_tab_colors(value: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
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


def check_drawer_arrangement_size(value: Optional[DrawerArrangement]) -> Optional[DrawerArrangement]:
    if value is None:
        return None
    json_size_cap(value.model_dump(mode="json"), MAX_DRAWER_ARRANGEMENT_BYTES, "drawer_arrangement is too large to store")
    return value


def check_collapsed_paths(value: Optional[Dict[str, bool]]) -> Optional[Dict[str, bool]]:
    if value is None:
        return None
    if len(value) > MAX_COLLAPSED_PATHS:
        raise ValueError(f"at most {MAX_COLLAPSED_PATHS} remembered tree nodes")
    for key in value:
        if not key or len(key) > MAX_KEY_LENGTH * 8:
            raise ValueError("a tree node key must be 1 to 1024 characters")
    return value


def check_launchpad_sections(value: Optional[Dict[str, bool]]) -> Optional[Dict[str, bool]]:
    if value is None:
        return None
    for key in value:
        if key not in LAUNCHPAD_SECTION_IDS:
            raise ValueError(
                f"launchpad_collapsed only covers {list(LAUNCHPAD_SECTION_IDS)}"
            )
    return value


def check_foot_bar_items(value: Optional[Dict[str, bool]]) -> Optional[Dict[str, bool]]:
    if value is None:
        return None
    for key in value:
        if key not in FOOT_BAR_ITEM_IDS:
            raise ValueError(f"foot_bar_items only covers {list(FOOT_BAR_ITEM_IDS)}")
    return value


def check_foot_bar_order(value: Optional[List[str]]) -> Optional[List[str]]:
    if value is None:
        return None
    if sorted(value) != sorted(FOOT_BAR_ORDER_IDS):
        raise ValueError(f"foot_bar_order must name each of {list(FOOT_BAR_ORDER_IDS)} exactly once")
    return list(value)


def check_layout_tabs(value: Optional[List[str]]) -> Optional[List[str]]:
    if value is None:
        return None
    if any(not isinstance(item, str) or not LAYOUT_TAB_ID_RE.match(item) for item in value):
        raise SidebarChecksError("layout_tabs holds saved-layout ids only")
    out = list(dict.fromkeys(value))
    if len(out) > MAX_LAYOUT_TABS:
        raise SidebarChecksError(f"at most {MAX_LAYOUT_TABS} layout tabs")
    return out


def check_stats_bar_rate(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in STATS_BAR_RATES:
        raise SidebarChecksError(f"stats_bar_rate must be one of {list(STATS_BAR_RATES)}")
    return value


def check_stats_bar_window(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in STATS_BAR_WINDOWS:
        raise SidebarChecksError(f"stats_bar_window must be one of {list(STATS_BAR_WINDOWS)}")
    return value


def _contains_secret_key(value: Any, depth: int = 0) -> bool:
    if depth > _MAX_PREF_JSON_DEPTH:
        return True
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or _SECRET_SUBKEY_RE.search(key):
                return True
            if _contains_secret_key(item, depth + 1):
                return True
    elif isinstance(value, list):
        for item in value:
            if _contains_secret_key(item, depth + 1):
                return True
    return False


def _check_bounded_filter_dict(
    value: Optional[Dict[str, Any]],
    *,
    field_name: str,
    max_keys: int,
    max_bytes: int,
) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SidebarChecksError(f"{field_name} must be an object")
    if len(value) > max_keys:
        raise SidebarChecksError(f"{field_name} holds at most {max_keys} keys")
    for key in value:
        if not isinstance(key, str) or not FILTER_KEY_RE.fullmatch(key) or ".." in key:
            raise SidebarChecksError(f"{field_name} contains an invalid filter key")
    if _contains_secret_key(value):
        raise SidebarChecksError(f"{field_name} cannot hold credential keys or excessive nesting")
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SidebarChecksError(f"{field_name} must contain finite JSON values") from exc
    if len(encoded) > max_bytes:
        raise SidebarChecksError(f"{field_name} exceeds {max_bytes} bytes")
    return dict(value)


def check_analytics_filters(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return _check_bounded_filter_dict(
        value,
        field_name="analytics_filters",
        max_keys=MAX_ANALYTICS_FILTER_KEYS,
        max_bytes=MAX_ANALYTICS_FILTERS_BYTES,
    )


def check_analytics_timezone(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_ANALYTICS_TIMEZONE_CHARS:
        raise SidebarChecksError(f"analytics_timezone must be 1 to {MAX_ANALYTICS_TIMEZONE_CHARS} characters")
    try:
        return app_time_zone.validate(value)
    except ValueError as exc:
        raise SidebarChecksError(str(exc)) from exc


def check_timeline_filters(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return _check_bounded_filter_dict(
        value,
        field_name="timeline_filters",
        max_keys=MAX_TIMELINE_FILTER_KEYS,
        max_bytes=MAX_TIMELINE_FILTERS_BYTES,
    )


def check_widget_state(value: Optional[Dict[str, Dict[str, Any]]]) -> Optional[Dict[str, Dict[str, Any]]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SidebarChecksError("widget_state must be an object mapping widget ids to state dicts")
    if len(value) > MAX_WIDGET_STATE_ENTRIES:
        raise SidebarChecksError(f"widget_state holds at most {MAX_WIDGET_STATE_ENTRIES} widgets")
    out: Dict[str, Dict[str, Any]] = {}
    for wid, state in value.items():
        if not isinstance(wid, str) or not WIDGET_STATE_ID_RE.fullmatch(wid) or ".." in wid:
            raise SidebarChecksError("widget_state keys must be valid widget ids (1 to 64 characters)")
        if not isinstance(state, dict):
            raise SidebarChecksError(f"widget_state[{wid!r}] must be an object")
        if _contains_secret_key(state):
            raise SidebarChecksError(f"widget_state[{wid!r}] cannot contain credential keys or excessive nesting")
        try:
            encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SidebarChecksError(f"widget_state[{wid!r}] must contain finite JSON values") from exc
        if len(encoded) > MAX_WIDGET_STATE_ENTRY_BYTES:
            raise SidebarChecksError(f"widget_state[{wid!r}] exceeds {MAX_WIDGET_STATE_ENTRY_BYTES} bytes")
        out[wid] = dict(state)
    return out

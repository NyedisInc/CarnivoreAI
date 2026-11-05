
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import ValidationInfo

from src.core.ui_preferences.checks import json_size_cap
from src.core.ui_preferences.constants import FOOT_BAR_ITEM_IDS, FOOT_BAR_ORDER_IDS, LAUNCHPAD_SECTION_IDS, MAX_COLLAPSED_PATHS, MAX_KEY_LENGTH, MAX_MENU_ORDER, MAX_SIDEBAR_TAB_COLORS, RAIL_MAGNIFY_PERCENTS, SIDEBAR_DENSITIES, SIDEBAR_LAYOUTS, SIDEBAR_TAB_COLOR_NAMES, SIDEBAR_TAB_ID_RE, WIDGET_DRAWER_VIEWS
from src.core.ui_preferences.drawer_arrangement import DrawerArrangement, MAX_DRAWER_ARRANGEMENT_BYTES


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

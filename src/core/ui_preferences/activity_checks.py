
from __future__ import annotations

from typing import List, Optional

from src.core.automations.ui_prefs import check_read_run_ids, check_seen_at
from src.core.ui_preferences.checks import json_size_cap
from src.core.ui_preferences.constants import DEEPSEARCH_INDEX_SCOPES, MAX_DISABLED_PLUGINS, MAX_HOME_LAYOUT_BYTES, MAX_TERMINAL_LAYOUTS_BYTES, TERMINAL_SCREEN_READER_MODES, TOAST_MODES
from src.core.ui_preferences.layouts import HomeLayout, TerminalLayouts
from src.cplugs.sdk import chat_category


def check_toast_mode(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in TOAST_MODES:
        raise ValueError(f"toast_mode must be one of {list(TOAST_MODES)}")
    return value


def check_terminal_screen_reader(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in TERMINAL_SCREEN_READER_MODES:
        raise ValueError(f"terminal_screen_reader must be one of {list(TERMINAL_SCREEN_READER_MODES)}")
    return value


def check_deepsearch_index_scope(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in DEEPSEARCH_INDEX_SCOPES:
        raise ValueError(f"deepsearch_index_scope must be one of {list(DEEPSEARCH_INDEX_SCOPES)}")
    return value


def check_swarm_chat_muted(value: Optional[List[str]]) -> Optional[List[str]]:
    return chat_category.check_muted(value)


def check_automation_runs_seen_at(value: Optional[str]) -> Optional[str]:
    return None if value is None else check_seen_at(value)


def check_warez_last_call(value: Optional[str]) -> Optional[str]:
    return None if value is None else check_seen_at(value)


def check_automation_runs_read(value: Optional[List[str]]) -> Optional[List[str]]:
    return None if value is None else check_read_run_ids(value)


def check_disabled_plugin_ids(value: Optional[List[str]]) -> Optional[List[str]]:
    if value is None:
        return None
    return list(dict.fromkeys(i for i in value if isinstance(i, str)))[:MAX_DISABLED_PLUGINS]


def check_terminal_layouts_size(value: Optional[TerminalLayouts]) -> Optional[TerminalLayouts]:
    if value is None:
        return None
    json_size_cap(value.model_dump(mode="json"), MAX_TERMINAL_LAYOUTS_BYTES, "terminal_layouts is too large to store")
    return value


def check_home_layout_size(value: Optional[HomeLayout]) -> Optional[HomeLayout]:
    if value is None:
        return None
    json_size_cap(value.model_dump(mode="json"), MAX_HOME_LAYOUT_BYTES, "home_layout is too large to store")
    return value

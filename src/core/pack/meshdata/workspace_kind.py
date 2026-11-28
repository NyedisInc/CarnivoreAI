
from __future__ import annotations

import json
import re
from typing import Any, FrozenSet, Optional, Tuple

from pydantic import ValidationError

from src.core.computers import direction
from src.core.row_looks import palette as row_looks_palette
from src.core.time_zone import app_time_zone
from src.core.ui_preferences.block import is_secret_name
from src.core.ui_preferences.constants import MAX_FOLDED_SECTIONS, MAX_KEY_LENGTH
from src.core.ui_preferences.drawer_arrangement import LAYOUT_PIN_RE, _RESERVED_FOLD_KEYS
from src.core.ui_preferences.values import UiPreferenceValues

KIND = "workspace"
CAP, ORIGIN_CAP, RESERVE = 16384, 8192, 2048
TOMB_TTL_MS = 30 * 24 * 3600 * 1000
MAX_KEY_LEN = 128
MAX_VALUE_BYTES = 4096
MAX_JSON_DEPTH = 8

SYNCED_TOP_PREFS: Tuple[str, ...] = (
    "sidebar_density",
    "sidebar_layout",
    "sidebar_show_leaders",
    "sidebar_show_archived",
    "sidebar_show_closed",
    "sidebar_list_open",
    "sidebar_list_sleeping",
    "sidebar_fold_sleeping",
    "sidebar_hide_empty_sections",
    "sidebar_show_stats",
    "drawer_row_icons",
    "drawer_zone",
    "menu_order",
    "rail_hidden_icons",
    "theme",
    "layout_tabs",
    "stats_bar_rate",
    "stats_bar_window",
    "analytics_filters",
    "analytics_timezone",
    "timeline_filters",
)

SYNCED_ARRANGEMENT_PREFS: Tuple[str, ...] = (
    "projects_open",
    "desktop_collapsed",
)

RESERVED_P3_PREFS: Tuple[str, ...] = ()

PREF_KEYS: FrozenSet[str] = frozenset((*SYNCED_TOP_PREFS, *SYNCED_ARRANGEMENT_PREFS, *RESERVED_P3_PREFS))

_BOOL_PREFS: FrozenSet[str] = frozenset({
    "sidebar_show_leaders",
    "sidebar_show_archived",
    "sidebar_show_closed",
    "sidebar_list_open",
    "sidebar_list_sleeping",
    "sidebar_fold_sleeping",
    "sidebar_hide_empty_sections",
    "sidebar_show_stats",
    "projects_open",
})
_STR_PREFS: FrozenSet[str] = frozenset({
    "sidebar_density",
    "sidebar_layout",
    "theme",
    "stats_bar_rate",
    "stats_bar_window",
})
_LIST_PREFS: FrozenSet[str] = frozenset({
    "menu_order",
    "rail_hidden_icons",
    "layout_tabs",
})
_DICT_PREFS: FrozenSet[str] = frozenset({
    "drawer_row_icons",
    "drawer_zone",
    "analytics_filters",
    "timeline_filters",
})

_EXTRA_SECRET_KEYS: FrozenSet[str] = frozenset({
    "secret_fields",
    "secret_rev",
    "auth",
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "private_key",
    "access_key",
    "session_token",
    "bearer",
    "jwt",
})

_SECRET_SUBSTR_RE = re.compile(
    r"(token|secret|password|passphrase|api[_-]?key|cookie|credential|private[_-]?key|access[_-]?key|bearer|jwt|(?:^|[_.-])auth(?:$|[_.-]))",
    re.I,
)

_UID32 = r"[0-9a-f]{32}"
_ROW_LOOK_ID = r"[0-9a-f]{16}"
_BOARD_ID = r"[A-Za-z0-9_-]{1,32}"
_SAFE_ID = r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,95}"
_SAFE_CELL = r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,80}"
_ROW_CHUNK = r"[0-9]{1,3}"

_PREF_KEY_RE = re.compile(r"^pref:(?P<name>[a-z][a-z0-9_]{0,63})$")
_ROW_LOOK_KEY_RE = re.compile(rf"^rl:(?P<rid>{_ROW_LOOK_ID})$")
_RESERVED_KEY_RE = re.compile(
    rf"^(?:(?P<db_meta>db:meta)"
    rf"|db:(?P<db_id>{_BOARD_ID}):(?P<db_part>head|rows|r\.(?P<chunk>{_ROW_CHUNK})|g\.(?P<cell>{_SAFE_CELL}))"
    rf"|(?P<res_prefix>sc|st|sa|ws|wst):(?P<res_id>{_SAFE_ID})"
    rf"|(?P<ss>ss:settings))$"
)

_PORTABLE_CO_FOLD_RE = re.compile(rf"^cu:{_UID32}$")
_PORTABLE_PROJ_FOLD_RE = re.compile(rf"^pu:{_UID32}(?::agents)?$")
_GROUP_FOLD_RE = re.compile(r"^g:[A-Za-z0-9][A-Za-z0-9._:-]{0,125}$")


def is_secret_field(key: str) -> bool:
    return is_secret_name(key) or key.lower() in _EXTRA_SECRET_KEYS or bool(_SECRET_SUBSTR_RE.search(key))


def strip_secret_keys(value: Any, depth: int = 0) -> Any:
    if depth > MAX_JSON_DEPTH:
        return {} if isinstance(value, dict) else []
    if isinstance(value, dict):
        return {
            k: strip_secret_keys(v, depth + 1)
            for k, v in value.items()
            if isinstance(k, str) and not is_secret_field(k)
        }
    if isinstance(value, list):
        return [strip_secret_keys(item, depth + 1) for item in value]
    return value


def _canonical_ok(value: Any) -> bool:
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        return False
    return len(text) <= MAX_VALUE_BYTES


def _has_secret_key(value: Any, depth: int = 0) -> bool:
    if depth > MAX_JSON_DEPTH:
        return True
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str) or is_secret_field(k):
                return True
            if _has_secret_key(v, depth + 1):
                return True
    elif isinstance(value, list):
        for item in value:
            if _has_secret_key(item, depth + 1):
                return True
    return False


def _valid_install_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 64
        and value.strip() == value
        and value.isprintable()
        and "/" not in value
        and "\\" not in value
        and ".." not in value
    )


def valid_portable_fold_key(key: Any) -> bool:
    if not isinstance(key, str) or not (1 <= len(key) <= MAX_KEY_LENGTH):
        return False
    if key in _RESERVED_FOLD_KEYS or key == "c:orphaned":
        return True
    if _PORTABLE_CO_FOLD_RE.fullmatch(key) or _PORTABLE_PROJ_FOLD_RE.fullmatch(key):
        return True
    if _GROUP_FOLD_RE.fullmatch(key) or LAYOUT_PIN_RE.fullmatch(key):
        return True
    if key.startswith("host-off:"):
        return _valid_install_id(key[9:])
    return False


def _valid_pref(name: str, value: Any) -> bool:
    if name not in PREF_KEYS:
        return False
    if value is None:
        return True
    if name in _BOOL_PREFS:
        return isinstance(value, bool)
    if name in _STR_PREFS:
        if not isinstance(value, str):
            return False
        try:
            UiPreferenceValues(**{name: value})
        except ValidationError:
            return False
        return True
    if name in _LIST_PREFS:
        if not isinstance(value, list) or not all(isinstance(i, str) for i in value) or len(set(value)) != len(value):
            return False
        try:
            UiPreferenceValues(**{name: value})
        except ValidationError:
            return False
        return True
    if name in _DICT_PREFS:
        if not isinstance(value, dict) or _has_secret_key(value):
            return False
        try:
            UiPreferenceValues(**{name: value})
        except ValidationError:
            return False
        return True
    if name == "desktop_collapsed":
        return (
            isinstance(value, list)
            and len(value) <= MAX_FOLDED_SECTIONS
            and len(set(value)) == len(value)
            and all(valid_portable_fold_key(item) for item in value)
        )
    if name == "analytics_timezone":
        if not isinstance(value, str) or len(value) > 64:
            return False
        try:
            app_time_zone.validate(value)
        except ValueError:
            return False
        return True
    return isinstance(value, dict) and not _has_secret_key(value)


def _valid_row_look(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if is_tomb(value):
        return True
    if not value or not (set(value) <= {"color", "icon"}):
        return False
    color = value.get("color")
    icon = value.get("icon")
    if color is None and icon is None:
        return False
    if color is not None and (not isinstance(color, str) or color not in row_looks_palette.COLORS):
        return False
    if icon is not None and (not isinstance(icon, str) or icon not in row_looks_palette.ICONS):
        return False
    return True


def valid_shape(v: Any) -> bool:
    return v is None or isinstance(v, (bool, str, list, dict))


def is_tomb(v: Any) -> bool:
    return isinstance(v, dict) and set(v) == {"gone"} and v.get("gone") is True


def valid(key: str, v: Any) -> bool:
    if not isinstance(key, str) or not (1 <= len(key) <= MAX_KEY_LEN) or not valid_shape(v):
        return False
    if not _canonical_ok(v):
        return False
    m_pref = _PREF_KEY_RE.fullmatch(key)
    if m_pref is not None:
        return _valid_pref(m_pref["name"], v)
    if _ROW_LOOK_KEY_RE.fullmatch(key) is not None:
        return _valid_row_look(v)
    m_res = _RESERVED_KEY_RE.fullmatch(key)
    if m_res is not None:
        for seg in (m_res["db_id"], m_res["cell"], m_res["res_id"]):
            if seg is not None and ".." in seg:
                return False
        if is_tomb(v):
            return m_res["ss"] is None
        if m_res["db_part"] == "rows":
            return isinstance(v, (dict, list)) and not _has_secret_key(v)
        return isinstance(v, dict) and not _has_secret_key(v)
    return False


def approved_listed(lst: Any, iid: Optional[str]) -> bool:
    entry = lst.entry(iid) if iid is not None and hasattr(lst, "entry") else None
    return entry is not None and not entry.one_way


def approved(lst: Any, iid: Optional[str]) -> bool:
    return approved_listed(lst, iid) and not direction.contained(iid)


def privileged(lst: Any, origin: Optional[str]) -> bool:
    return origin is not None and origin in (lst.alpha, lst.home)


def origin_ok(lst: Any, origin: Optional[str]) -> bool:
    return approved_listed(lst, origin)


def serve_ok(lst: Any, peer: Optional[str]) -> bool:
    return approved(lst, peer)

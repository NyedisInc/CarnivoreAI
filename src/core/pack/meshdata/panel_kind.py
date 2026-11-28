
from __future__ import annotations

import json
import re
from typing import Any, Optional

from src.core import session_group_style as style_store
from src.core.computers import direction
from src.core.db_models import SESSION_GROUP_NAME_MAX
from src.core.layouts import store as layouts_store
from src.core.pack.globalsync import panel
from src.core.project_colors.palette import is_hex_color
from src.core.session_groups import session_group_rule as rule_store
from src.core.ui_preferences.drawer_arrangement import SECTION_IDS

KIND = "panel"
CAP, ORIGIN_CAP, RESERVE = 32768, 16384, 4096
TOMB_TTL_MS = 30 * 24 * 3600 * 1000
MAX_SHORT_DESCRIPTION = 200
MAX_DICT_BYTES = 4096
MAX_PARENT_KEY = 128
MAX_ICON_LEN = 64

_UID = r"[0-9a-f]{32}"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_BANDS = "|".join(sorted(panel._KIND_BANDS))
_KEY = re.compile(
    rf"(?:c:(?P<cuid>{_UID}):(?P<cf>name|parent_uid|hue|gone)"
    rf"|p:(?P<puid>{_UID}):(?P<pf>name|company_uid|color|short_description|archived|parent_uid|home_iid)"
    rf"|g:(?P<guid>{_UUID}):(?P<gf>name|parent_key|style|icon|rule|gone)"
    rf"|ly:(?P<lyuid>{_UUID}):(?P<lyf>name|shape|style|gone)"
    rf"|(?P<sections>a:sections)"
    rf"|l:(?P<list>pin|ord|go|lo|b\.(?:{_BANDS})|b\.p\.{_UID}|gm\.{_UUID}|gb\.{_UUID}|lm\.{_UUID}):(?P<item>{_UUID}/{_UUID}|ly/{_UUID}|{_UUID}))"
)
_POS = re.compile(r"[0-9A-Za-z]{1,64}")
_ITEM_PAIR = re.compile(rf"{_UUID}/{_UUID}")
_ITEM_LY = re.compile(rf"ly/{_UUID}")
_ITEM_UUID = re.compile(_UUID)


def _json_size(v: Any) -> int:
    try:
        return len(json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False))
    except (ValueError, TypeError, RecursionError):
        return MAX_DICT_BYTES + 1


def _valid_install_id(v: Any) -> bool:
    return v is None or (isinstance(v, str) and 0 < len(v) <= 64 and v.strip() == v and v.isprintable()
                         and "/" not in v and "\\" not in v and ".." not in v)


def _text(v: Any, limit: int) -> bool:
    return v is None or (isinstance(v, str) and 0 < len(v) <= limit)


def _valid_pos_val(v: Any, *, allow_bc: bool) -> bool:
    if not isinstance(v, dict) or "pos" not in v:
        return False
    allowed = {"pos", "bc"} if allow_bc else {"pos"}
    if not set(v) <= allowed:
        return False
    pos = v["pos"]
    if pos is not None and not (isinstance(pos, str) and _POS.fullmatch(pos) is not None):
        return False
    if "bc" in v and not isinstance(v["bc"], bool):
        return False
    return True


def _valid_style_dict(v: Any) -> bool:
    if v is None:
        return True
    if not isinstance(v, dict) or _json_size(v) > MAX_DICT_BYTES:
        return False
    if "colour" not in v or not set(v) <= {"colour", "gradient", "animation"}:
        return False
    if not style_store.valid_colour(v["colour"]):
        return False
    gradient = v.get("gradient")
    if gradient is not None and gradient not in style_store.GRADIENTS:
        return False
    animation = v.get("animation", "none")
    return isinstance(animation, str) and animation in style_store.ANIMATIONS


def _valid_rule_dict(v: Any) -> bool:
    if v is None:
        return True
    if not isinstance(v, dict) or _json_size(v) > MAX_DICT_BYTES or not set(v) <= {"flags", "prefix", "suffix"}:
        return False
    flags = v.get("flags", [])
    if not isinstance(flags, list) or not all(isinstance(f, str) and f in rule_store.FLAGS for f in flags):
        return False
    for key in ("prefix", "suffix"):
        val = v.get(key)
        if val is not None and (not isinstance(val, str) or len(val) > rule_store.TEXT_MAX):
            return False
    return True


def valid_shape(v: Any) -> bool:
    if v is None or isinstance(v, (bool, int, str)):
        return True
    if isinstance(v, list):
        return len(v) <= len(SECTION_IDS) and all(isinstance(i, str) for i in v)
    if isinstance(v, dict):
        if "pos" in v:
            return _valid_pos_val(v, allow_bc=True)
        return _json_size(v) <= MAX_DICT_BYTES
    return False


def valid(key: str, v: Any) -> bool:
    m = _KEY.fullmatch(key) if isinstance(key, str) else None
    if m is None:
        return False
    if m["cf"] or m["pf"] or m["gf"]:
        field = m["cf"] or m["pf"] or m["gf"]
        if field == "name":
            return _text(v, SESSION_GROUP_NAME_MAX if m["guid"] else panel.MAX_NAME)
        if field == "hue":
            return v is None or (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 359)
        if field in ("parent_uid", "company_uid"):
            return v is None or (isinstance(v, str) and re.fullmatch(_UID, v) is not None)
        if field == "color":
            return v is None or is_hex_color(v)
        if field == "short_description":
            return v is None or (isinstance(v, str) and len(v) <= MAX_SHORT_DESCRIPTION)
        if field == "home_iid":
            return _valid_install_id(v)
        if field == "parent_key":
            return v is None or (isinstance(v, str) and 0 < len(v) <= MAX_PARENT_KEY and v.strip() == v and v.isprintable())
        if field == "icon":
            return v is None or (isinstance(v, str) and 0 < len(v) <= MAX_ICON_LEN and v.strip() == v and v.isprintable())
        if field == "style":
            return _valid_style_dict(v)
        if field == "rule":
            return _valid_rule_dict(v)
        return isinstance(v, bool)
    if m["lyf"]:
        field = m["lyf"]
        if field == "name":
            return _text(v, layouts_store.NAME_MAX)
        if field == "shape":
            return v is None or (isinstance(v, (dict, str)) and _json_size(v) <= MAX_DICT_BYTES)
        if field == "style":
            return _valid_style_dict(v)
        return isinstance(v, bool)
    if m["sections"]:
        return v is None or (isinstance(v, list) and len(set(v)) == len(v) and all(i in SECTION_IDS for i in v))
    list_id, item = m["list"], m["item"]
    if list_id in ("go", "lo"):
        return _ITEM_UUID.fullmatch(item) is not None and _valid_pos_val(v, allow_bc=False)
    if list_id.startswith("lm."):
        return _ITEM_PAIR.fullmatch(item) is not None and _valid_pos_val(v, allow_bc=True)
    if list_id == "pin" or list_id.startswith(("gm.", "gb.")):
        return (_ITEM_PAIR.fullmatch(item) is not None or _ITEM_LY.fullmatch(item) is not None) and _valid_pos_val(v, allow_bc=False)
    return _ITEM_PAIR.fullmatch(item) is not None and _valid_pos_val(v, allow_bc=False)


def is_tomb(v: Any) -> bool:
    return isinstance(v, dict) and "pos" in v and set(v) <= {"pos", "bc"} and v["pos"] is None


def approved_listed(lst: Any, iid: Optional[str]) -> bool:
    entry = lst.entry(iid) if iid is not None and hasattr(lst, "entry") else None
    return entry is not None and not entry.one_way


def approved(lst: Any, iid: Optional[str]) -> bool:
    return approved_listed(lst, iid) and not direction.contained(iid)


def privileged(lst: Any, origin: Optional[str]) -> bool:
    return origin is not None and origin in (lst.alpha, lst.home)


def origin_ok(lst: Any, origin: str) -> bool:
    return approved_listed(lst, origin)


def serve_ok(lst: Any, peer: Optional[str]) -> bool:
    return approved(lst, peer)

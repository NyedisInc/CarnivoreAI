
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, ValidationInfo, field_validator, model_serializer, model_validator

from src.core.layouts import tree_v7 as layout_tree_v7
from src.core import theme_script_consent
from src.core.desktop_app import preferences as desktop_preferences
from src.core.time_zone import app_time_zone
from src.core.automations.ui_prefs import check_read_run_ids, check_seen_at
from src.core.attention.kinds_choice import AttentionKindsChoice
from src.core.widget_placement.glance import GlancePlacement, OptionValue, check_option_values, check_placements
from src.core.widget_placement.retired_widgets import migrate_retired_placements
from src.core.widget_placement.widget_bars import WidgetBars
from src.cplugs.sdk import chat_category

UI_PREFERENCES_KEY = "ui_preferences"
"""The top-level config.json key this block lives under."""

SCHEMA_VERSION = 1
"""Bumped only for a shape change readers must branch on. A new FIELD is
additive and needs no bump: an older client ignores what it does not
know and a newer server preserves what it does not know."""

SIDEBAR_DENSITIES = ("compact", "cozy", "detailed")
WIDGET_DRAWER_VIEWS = ("type", "name")
SIDEBAR_LAYOUTS = ("classic", "rail")
TOAST_MODES = ("compact", "detailed")
TERMINAL_SCREEN_READER_MODES = ("auto", "on", "off")
DEEPSEARCH_INDEX_SCOPES = ("human", "human+subsessions", "all")
LAUNCHPAD_SECTION_IDS = ("running-sessions", "recent-sessions", "recent-projects")

FOOT_BAR_ITEM_IDS = (
    "model", "effort", "context", "window_5h", "window_7d", "agents", "shells", "timers",
)
"""The eight items the collapsed terminal foot bar can show or hide (issue
#1053), mirrored client side in
XX``FOOT_BAR_ITEM_IDS``. The two lists must stay identical: a server id this
client build has never heard of would validate and then never be settable
from the one control that writes this field."""

FOOT_BAR_ORDER_IDS = ("context", "window_5h", "window_7d")

RETIRED_FIELDS = (
    "header_quicklinks", "automations_show_huddle", "crosstalk_cards_sent", "crosstalk_cards_received", "wake_on_click",
    "sidebar_show_colors", "sidebar_show_colors_mobile",
)

FOOT_BAR_LAYOUT_OPTIONS = ("a", "b", "c")

THEME_ID_RE = theme_script_consent.THEME_ID_RE

MODEL_ID_RE = re.compile(r"^(?!-)[A-Za-z0-9._~/-]{1,120}$")

ARRANGEMENT_SCHEMA_VERSION = 1
MAX_REMEMBERED = 200
MAX_FOLDS = 100
"""The bounds ``session-sidebar-store.js`` already enforces locally,
restated here rather than inferred, so a hand-edited config cannot put
more into the block than the client will ever read back out."""

MAX_FOLDED_SECTIONS = 1000
"""Most fold keys in ``collapsed``. A Shift+click cascade folds every company and
project at once, so this is larger than the band-order bound ``MAX_FOLDS``;
the client mirrors it as ``MAX_FOLDS`` in ``store-keys.ts``."""

MAX_THEME_FAVORITES = 200
"""More than every theme an install can plausibly carry (40 bundled today),
so the cap bounds a hand-edited config rather than a real user."""
MAX_SKILL_FAVORITES = 200
MAX_SKILL_NAME_CHARS = 200


MAX_DRAWER_ZONE_ITEMS = 12
MAX_SESSION_RAIL_ITEMS = 256
MAX_SESSION_RAIL_SECTIONS = 2
SESSION_RAIL_RATIO_MIN = 0.15
SESSION_RAIL_RATIO_MAX = 0.85

DRAWER_ZONE_WIDGET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

SIDEBAR_TAB_COLOR_NAMES = ("orange", "green", "cyan", "yellow", "coral", "violet")

SIDEBAR_TAB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

MAX_SIDEBAR_TAB_COLORS = 64

DRAWER_ZONE_LOOKS = ("compact", "full")
DRAWER_ZONE_TARGET_RE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9:@._-]{0,127}$")
DRAWER_ZONE_VIEW_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")

DRAWER_ZONE_INSTANCE_RE = re.compile(r"^i[0-9]{1,3}$")

MAX_DRAWER_ZONE_ITEM_OPTIONS = 32
"""One slot per known id at most; a longer list could only be padded with
repeats, which the validator below already collapses."""

MAX_COLLAPSED_PATHS = 2000

# the built-in login
BUILTIN_LOGIN_LABEL_MAX = 40

OWNER_DISPLAY_NAME_MAX = 60
"""Longest name the drawer's account chip is asked to hold."""

MAX_DISABLED_PLUGINS = 200
"""Far more plugins than a build ships (three today); bounds a hand-edited
config rather than a real user."""

MAX_TERMINAL_LAYOUTS = 32
"""Mirrors ``web/src/opscenter/engine/session-layouts.ts::MAX_SESSION_LAYOUTS``:
the browser keeps the most recently used 32 session layouts and evicts the
oldest, so the synced map is bounded the same way (a cap, not a prune, for
the reason that file gives: ``/sessions/list`` carries no completeness
signal to prune against)."""
MAX_TAB_GROUPS = 64
MAX_TABS_PER_GROUP = 64
MAX_LAYOUT_BYTES = 16384
"""Mirrors ``persist.ts::MAX_BYTES``, the browser's own cap on one stored
layout, so the server never accepts a grid the client would refuse."""
MAX_TERMINAL_LAYOUTS_BYTES = 262144
MAX_HOME_LAYOUT_BYTES = 262144
MAX_HOME_BOARDS = 12
"""Most named Home boards one account keeps."""
HOME_BOARD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
"""A board id: the first board is ``home``, the rest are minted by the browser."""
MAX_HOME_BOARD_NAME = 40
MAX_ANALYTICS_SEED = 2
"""Highest seeding level the Home page knows (``analytics/state.svelte.ts``):
0 none, 1 first default charts, 2 the full default dashboard."""
TAB_ID_RE = re.compile(r"^terminal:[A-Za-z0-9@._:-]{1,120}$")
"""A tab or group slot id: ``terminal:@primary`` or ``terminal:<session id>``."""
PAGE_TAB_ID_RE = re.compile(r"^page:[0-9a-f]{16}$")
"""A page tab id (``web/src/opscenter/engine/page-tabs.ts``, issue #1787): ``page:`` and the 16 lowercase
hex characters of the browser, page or file it holds. A TAB may be one; a group SLOT never is (a page split
out lives in a ``terminal:pg-<id>`` component)."""
WIDGET_TAB_ID_RE = re.compile(r"^widget:[a-z0-9][a-z0-9._-]{0,63}$")
MAX_UNKNOWN_FIELDS = 64
MAX_KEY_LENGTH = 128
MAX_MENU_ORDER = 64
MAX_UNKNOWN_VALUE_BYTES = 8192

_RESERVED_FOLD_KEYS = frozenset(
    {"pinned", "other", "rogue", "terminals", "browsers", "files", "review", "ledger_hidden", "ledger_expanded",
     "ledger_glance", "layouts", "companies", "groups", "pack", "open", "sleeping"}
)

SECTION_IDS = ("pinned", "layouts", "groups", "companies", "rogue", "terminals", "browsers", "review", "pack")

_SECRET_KEY_NAMES = frozenset(
    {"claude_tunnel_token", "claude_refresh_token", "provider_accounts"}
)
_SECRET_KEY_SHAPE = re.compile(r"(token|secret|password|passphrase|api[_-]?key)", re.I)


class SidebarArrangement(BaseModel):
    """The sidebar's pinned set, explicit order and folded sections, BY NAME.

    Attributes:
      v (int): the envelope version ``session-sidebar-store.js`` writes.
      pinned (list[str]): session names, newest-first, capped at
        ``MAX_REMEMBERED``.
      order (list[str]): session names in the user's explicit order,
        capped the same way.
      collapsed (list[str]): ``"pinned"``, ``"other"``, ``"rogue"``,
        ``"terminals"``, ``"browsers"``, a ``"g:<uuid>"`` / ``"p:<id>"``
        fold key, or a ``"layout:<uuid>"`` per-layout fold (issue #802).
        Validated STRUCTURALLY and never against a live group or
        project list, because both load asynchronously after this parse
        runs - the same reason the client validates it that way
        (``client/js/session-sidebar-store.js::isFoldKey``). ``rogue`` and
        ``"p:<id>"`` were a pre-existing gap - the client has written them
        since the PROJECTS super-heading shipped, and this validator
        refused both until issue #448 slice S3 closed it alongside adding
        ``terminals``/``browsers`` for the new TERMINALS section. This
        model is superseded by ``DrawerArrangement`` (below) but a
        stored snapshot can carry a ``"layout:<uuid>"`` fold the
        DrawerArrangement-era client wrote (issue #1105); ``_bounded_folds`` delegates to the SAME ``_fold_key``
        shape check ``DrawerArrangement.collapsed`` uses so the two models
        never diverge on what a fold key looks like.
    """

    model_config = ConfigDict(extra="forbid")

    v: int = ARRANGEMENT_SCHEMA_VERSION
    pinned: List[str] = Field(default_factory=list)
    order: List[str] = Field(default_factory=list)
    collapsed: List[str] = Field(default_factory=list)

    @field_validator("pinned", "order")
    @classmethod
    def _bounded_names(cls, value: List[str]) -> List[str]:
        if len(value) > MAX_REMEMBERED:
            raise ValueError(f"at most {MAX_REMEMBERED} remembered session names")
        for name in value:
            if not name or len(name) > MAX_KEY_LENGTH:
                raise ValueError("a session name must be 1 to 128 characters")
        return value

    @field_validator("collapsed")
    @classmethod
    def _bounded_folds(cls, value: List[str]) -> List[str]:
        if len(value) > MAX_FOLDED_SECTIONS:
            raise ValueError(f"at most {MAX_FOLDED_SECTIONS} folded sections")
        for key in value:
            if not _fold_key(key):
                raise ValueError(f"unknown fold key '{key[:MAX_KEY_LENGTH]}'")
        return value


SESSION_UUID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{0,63}$")
"""A ``sessions.session_uuid``, the same shape ``src/config/auto_sleep.py``
accepts for ``keep_awake``."""
MAX_DRAWER_ARRANGEMENT_BYTES = 262144
"""The whole field serialised; it rides every ``preferences.changed`` frame."""
_BAND_ORDER_KEYS = frozenset({"rogue", "terminals", "browsers", "files", "review"})


LAYOUT_PIN_RE = re.compile(r"^layout:[0-9A-Za-z][0-9A-Za-z-]{0,63}$")
"""A pinned saved Layout (issue #424): ``layout:<layouts.layout_uuid>``.
Accepted in ``pinned`` only; every other list holds session uuids."""

COMPANY_FOLD_RE = re.compile(r"c:(?:[0-9]{1,18}|orphaned)")
"""A company heading's fold key (issue #1338): ``c:<company id>``, or ``c:orphaned`` for the
heading of projects filed under no company. Matched with ``fullmatch`` so a trailing newline fails."""


def _pin_list(value: List[str]) -> List[str]:
    if len(value) > MAX_REMEMBERED:
        raise ValueError(f"at most {MAX_REMEMBERED} pins")
    for item in value:
        if not (SESSION_UUID_RE.match(item) or LAYOUT_PIN_RE.match(item)):
            raise ValueError("pinned holds session uuids and 'layout:<uuid>' pins only")
    return list(dict.fromkeys(value))


def _uuid_list(value: List[str], what: str) -> List[str]:
    if len(value) > MAX_REMEMBERED:
        raise ValueError(f"at most {MAX_REMEMBERED} {what}")
    for item in value:
        if not SESSION_UUID_RE.match(item):
            raise ValueError(f"{what} holds session uuids only")
    return list(dict.fromkeys(value))


def _fold_key(key: str) -> bool:
    if key in _RESERVED_FOLD_KEYS:
        return True
    if key.startswith(("g:", "p:")) and 2 < len(key) <= MAX_KEY_LENGTH:
        return True
    if key.startswith("host-off:") and 9 < len(key) <= MAX_KEY_LENGTH:
        return True
    return bool(LAYOUT_PIN_RE.match(key) or COMPANY_FOLD_RE.fullmatch(key))


def _check_folds(value: List[str]) -> List[str]:
    if len(value) > MAX_FOLDED_SECTIONS:
        raise ValueError(f"at most {MAX_FOLDED_SECTIONS} folded sections")
    for key in value:
        if not _fold_key(key):
            raise ValueError(f"unknown fold key '{key[:MAX_KEY_LENGTH]}'")
    return list(dict.fromkeys(value))


class DrawerViewState(BaseModel):
    """
    Today that is the fold list alone; the phone's own folds, including the
    PROVIDERS panel's reserved ``ledger_*`` keys. See ``DrawerArrangement.mobile``.

    Attributes:
      collapsed (list[str]): folded section keys, validated by the same rule
        as ``DrawerArrangement.collapsed``.
    """

    model_config = ConfigDict(extra="forbid")

    collapsed: List[str] = Field(default_factory=list)

    @field_validator("collapsed")
    @classmethod
    def _folds(cls, value: List[str]) -> List[str]:
        return _check_folds(value)


class DrawerArrangement(BaseModel):
    """The sidebar and agents drawer arrangement, shared by every device.
    """

    model_config = ConfigDict(extra="forbid")

    v: int = ARRANGEMENT_SCHEMA_VERSION
    pinned: List[str] = Field(default_factory=list)
    order: List[str] = Field(default_factory=list)
    bands: Dict[str, List[str]] = Field(default_factory=dict)
    collapsed: List[str] = Field(default_factory=list)
    projects_open: Optional[bool] = None
    mobile: Optional[DrawerViewState] = None
    sections: Optional[List[str]] = None

    @field_validator("sections")
    @classmethod
    def _sections(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        for item in value:
            if item not in SECTION_IDS:
                raise ValueError(f"unknown drawer section '{item[:MAX_KEY_LENGTH]}'")
        if len(set(value)) != len(value):
            raise ValueError("a drawer section is listed twice")
        return value

    @field_validator("pinned")
    @classmethod
    def _pins(cls, value: List[str]) -> List[str]:
        return _pin_list(value)

    @field_validator("order")
    @classmethod
    def _uuids(cls, value: List[str]) -> List[str]:
        return _uuid_list(value, "remembered sessions")

    @field_validator("bands")
    @classmethod
    def _bands(cls, value: Dict[str, List[str]]) -> Dict[str, List[str]]:
        if len(value) > MAX_FOLDS:
            raise ValueError(f"at most {MAX_FOLDS} band orders")
        out: Dict[str, List[str]] = {}
        for key, uuids in value.items():
            if key in ("pinned", "other", "layouts") or not (key in _BAND_ORDER_KEYS or _fold_key(key)):
                raise ValueError(f"unknown band key '{key[:MAX_KEY_LENGTH]}'")
            out[key] = _uuid_list(uuids, "band members")
        return out

    @field_validator("collapsed")
    @classmethod
    def _folds(cls, value: List[str]) -> List[str]:
        return _check_folds(value)


DRAWER_ROW_ICON_DEFAULTS: Dict[str, bool] = {"compact": False, "cozy": True, "detailed": True}

DRAWER_ROW_EXTRA_ICON_DEFAULT: bool = True

DRAWER_ROW_EXTRA_ICON_KEYS: tuple = ("cup", "pin", "menu")

DRAWER_ROW_CONTEXT_GAUGE_DEFAULT: bool = True

DRAWER_ROW_AUTOMATIONS_DEFAULT: bool = True


class DrawerRowIconSet(BaseModel):
    """Which of a row's six optional controls show, for one density.

    The green "update ready" icon itself is NOT governed by this
    preference and always shows regardless of any of these six.
    """

    model_config = ConfigDict(extra="forbid")

    agents: Optional[bool] = None
    shells: Optional[bool] = None
    timers: Optional[bool] = None
    cup: Optional[bool] = None
    pin: Optional[bool] = None
    menu: Optional[bool] = None
    context: Optional[bool] = None
    automations: Optional[bool] = None


class DrawerRowIcons(BaseModel):
    """Per-density visibility of the drawer row's agents/shells/timers icons.
    """

    model_config = ConfigDict(extra="forbid")

    compact: Optional[DrawerRowIconSet] = None
    cozy: Optional[DrawerRowIconSet] = None
    detailed: Optional[DrawerRowIconSet] = None


class DrawerZoneItem(BaseModel):
    """One widget instance in the drawer's bottom widget area.

    Attributes:
      widget (str): the widget id, ``core.ledger``.
      look (str | None): ``compact`` or ``full``; None = the widget's own
        default for this surface (the providers widget draws compact here).
      target (str | None): what a FAMILY copy (terminal, browser, analytics)
        shows, the tail of its slot id; None for a singleton. A widget may
        appear more than once only with different targets.
      view (str | None): which VIEW of a widget with views this placement
        shows (``session`` or ``all`` for tasks, bookmarks, automations and
        Task Manager; ``docs/widget-system.md`` section 17); None = the widget's
        first view. The client validates the id against the widget's manifest.
      instance (str | None): which COPY of a widget placed more than once
        this is (``i2``, ``i3``; widgets with views may repeat, each copy
        with its own view); None = the first copy, so a placement stored
        before copies existed keeps its identity.
      options (dict | None): placement-scoped options of THIS copy (the
        questions widget's switches, one per source it may list), the same
        value shapes and key spelling as a glance placement's options
        (``widget_placement/glance.py``); None or absent = every option on its
        default. Which keys a widget understands is its own declaration; one a
        build does not know is kept.
    """

    model_config = ConfigDict(extra="forbid")

    widget: str
    look: Optional[str] = None
    target: Optional[str] = None
    view: Optional[str] = None
    instance: Optional[str] = None
    options: Optional[Dict[str, OptionValue]] = None

    @field_validator("options")
    @classmethod
    def _options(cls, value: Optional[Dict[str, OptionValue]]) -> Optional[Dict[str, OptionValue]]:
        return None if value is None else check_option_values(value, MAX_DRAWER_ZONE_ITEM_OPTIONS)

    @field_validator("instance")
    @classmethod
    def _instance(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not DRAWER_ZONE_INSTANCE_RE.match(value):
            raise ValueError("a drawer area instance is a copy id like 'i2'")
        return value

    @field_validator("view")
    @classmethod
    def _view(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not DRAWER_ZONE_VIEW_RE.match(value):
            raise ValueError("a drawer area view is a flat lowercase id like 'all'")
        return value

    @field_validator("target")
    @classmethod
    def _target(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not DRAWER_ZONE_TARGET_RE.match(value):
            raise ValueError("a drawer area target is a slot id tail like 'row:7'")
        return value

    @field_validator("widget")
    @classmethod
    def _widget_id(cls, value: str) -> str:
        if not DRAWER_ZONE_WIDGET_ID_RE.match(value):
            raise ValueError("a drawer area widget is an id like 'core.ledger'")
        return value

    @field_validator("look")
    @classmethod
    def _look(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in DRAWER_ZONE_LOOKS:
            raise ValueError(f"look must be one of {list(DRAWER_ZONE_LOOKS)}")
        return value


class DrawerZone(BaseModel):
    """The drawer's bottom widget area: an ORDERED list of widget instances.
    """

    model_config = ConfigDict(extra="forbid")

    v: int = 1
    items: List[DrawerZoneItem] = Field(default_factory=list)
    glance: Optional[List[GlancePlacement]] = None

    @field_validator("items")
    @classmethod
    def _items(cls, value: List[DrawerZoneItem]) -> List[DrawerZoneItem]:
        if len(value) > MAX_DRAWER_ZONE_ITEMS:
            raise ValueError(f"at most {MAX_DRAWER_ZONE_ITEMS} drawer area widgets")
        seen = set()
        for item in value:
            key = (item.widget, item.target, item.instance)
            if key in seen:
                raise ValueError("a widget (or a family copy's target) appears in the drawer area once per copy id")
            seen.add(key)
        return value

    @field_validator("glance")
    @classmethod
    def _glance(cls, value: Optional[List[GlancePlacement]]) -> Optional[List[GlancePlacement]]:
        return check_placements(value)



class SessionRailSection(BaseModel):
    """One section of a split session rail: an ordered list of widget instances (issue #1472)."""

    model_config = ConfigDict(extra="forbid")

    items: List[DrawerZoneItem] = Field(default_factory=list)


class SessionRail(BaseModel):
    """The session view's widget rail: an ORDERED list of widget instances, in one or two sections (issue #1472).
    """

    model_config = ConfigDict(extra="forbid")

    v: int = 1
    items: Optional[List[DrawerZoneItem]] = None
    sections: Optional[List[SessionRailSection]] = None
    ratio: Optional[float] = None

    @model_validator(mode="after")
    def _shape(self) -> "SessionRail":
        if self.v == 1:
            if self.sections is not None or self.ratio is not None:
                raise ValueError("a v1 session rail is a flat list: items only")
            if self.items is None:
                self.items = []
            flat = list(self.items)
        elif self.v == 2:
            if self.items is not None or self.sections is None:
                raise ValueError("a v2 session rail holds sections, not items")
            if not 1 <= len(self.sections) <= MAX_SESSION_RAIL_SECTIONS:
                raise ValueError(f"a session rail has 1 to {MAX_SESSION_RAIL_SECTIONS} sections")
            split = len(self.sections) == 2
            if split and any(not section.items for section in self.sections):
                raise ValueError("a split session rail has widgets in both sections")
            if (self.ratio is not None) != split:
                raise ValueError("a session rail carries a ratio exactly when it is split")
            if split and not SESSION_RAIL_RATIO_MIN <= float(self.ratio) <= SESSION_RAIL_RATIO_MAX:
                raise ValueError(f"the split ratio is between {SESSION_RAIL_RATIO_MIN} and {SESSION_RAIL_RATIO_MAX}")
            flat = [item for section in self.sections for item in section.items]
        else:
            raise ValueError("a session rail is version 1 or 2")
        if len(flat) > MAX_SESSION_RAIL_ITEMS:
            raise ValueError(f"at most {MAX_SESSION_RAIL_ITEMS} session rail widgets")
        seen = set()
        for item in flat:
            key = (item.widget, item.target, item.instance)
            if key in seen:
                raise ValueError("a widget (or a family copy's target) appears in the session rail once per copy id")
            seen.add(key)
        return self


class FootBarLayout(BaseModel):
    """Which built layout each half of the terminal foot bar draws.

    Attributes:
      collapsed (str | None): 'a' (meters first), 'b' (a status line
        grouped by scope) or 'c' (attention first). None = 'a'.
      open (str | None): 'a' (band + three columns), 'b' (a tabs rail) or
        'c' (one list grouped by owner). None = 'a'.
    """

    model_config = ConfigDict(extra="forbid")

    collapsed: Optional[str] = None
    open: Optional[str] = None

    @field_validator("collapsed", "open")
    @classmethod
    def _option(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in FOOT_BAR_LAYOUT_OPTIONS:
            raise ValueError(f"foot_bar_layout options are {list(FOOT_BAR_LAYOUT_OPTIONS)}")
        return value


def drawer_row_icons_defaults() -> Dict[str, Dict[str, bool]]:
    return {
        density: {
            "agents": shown,
            "shells": shown,
            "timers": shown,
            **{key: DRAWER_ROW_EXTRA_ICON_DEFAULT for key in DRAWER_ROW_EXTRA_ICON_KEYS},
            "context": DRAWER_ROW_CONTEXT_GAUGE_DEFAULT,
            "automations": DRAWER_ROW_AUTOMATIONS_DEFAULT,
        }
        for density, shown in DRAWER_ROW_ICON_DEFAULTS.items()
    }


class TerminalTabGroup(BaseModel):
    """One component's tabs, in strip order (``engine/tabs.ts::TabGroup``)."""

    model_config = ConfigDict(extra="forbid")

    tabs: List[str] = Field(default_factory=list)

    @field_validator("tabs")
    @classmethod
    def _bounded_tabs(cls, value: List[str]) -> List[str]:
        if len(value) > MAX_TABS_PER_GROUP:
            raise ValueError(f"at most {MAX_TABS_PER_GROUP} tabs in one component")
        for tab in value:
            if not (TAB_ID_RE.match(tab) or PAGE_TAB_ID_RE.match(tab) or WIDGET_TAB_ID_RE.match(tab)):
                raise ValueError("a tab id reads 'terminal:<session id>', 'page:<16 hex>' or 'widget:<widget id>'")
        return value


class TerminalLayoutEntry(BaseModel):
    """One session's terminal page arrangement: its grid and its tab groups.

    Attributes:
      layout (dict | None): the grid, or None for the pane alone. Either
        shape is accepted (issue #724, slice 2): a v6 grid
        (``engine/types.ts::Layout``: an integer ``v`` and a non-empty
        ``rows`` list) or a v7 split tree (``engine/v7/types.ts``, ``v``
        7), checked by ``layout_tree_v7.check_layout``. Both at most
        ``MAX_LAYOUT_BYTES`` serialised. Checked STRUCTURALLY here; the
        browser's own ``validate`` is the full check and runs on every
        apply, so a grid this server accepts and that browser refuses
        opens on the pane alone.
      groups (dict): component slot id to its ``TerminalTabGroup``.
    """

    model_config = ConfigDict(extra="forbid")

    layout: Optional[Dict[str, Any]] = None
    groups: Dict[str, TerminalTabGroup] = Field(default_factory=dict)

    @field_validator("layout")
    @classmethod
    def _bounded_layout(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        version = value.get("v")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError("a terminal layout carries an integer 'v'")
        if len(json.dumps(value).encode("utf-8")) > MAX_LAYOUT_BYTES:
            raise ValueError("a terminal layout is too large to store")
        if layout_tree_v7.is_v7(value):
            try:
                layout_tree_v7.check_layout(value)
            except layout_tree_v7.TreeInvalid as exc:
                raise ValueError(f"a v7 terminal layout is not a split tree: {exc}") from None
            return value
        rows = value.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ValueError("a terminal layout carries a non-empty 'rows' list")
        return value

    @field_validator("groups")
    @classmethod
    def _bounded_groups(cls, value: Dict[str, TerminalTabGroup]) -> Dict[str, TerminalTabGroup]:
        if len(value) > MAX_TAB_GROUPS:
            raise ValueError(f"at most {MAX_TAB_GROUPS} tab groups in one layout")
        for slot in value:
            if not TAB_ID_RE.match(slot):
                raise ValueError("a tab group slot reads 'terminal:<id>'")
        return value


class TerminalLayouts(BaseModel):
    """The terminal page's per session arrangements, synced across devices.

    Attributes:
      v (int): the envelope version.
      sessions (dict): layout key to its ``TerminalLayoutEntry``, at most
        ``MAX_TERMINAL_LAYOUTS``, in least to most recently written order.
    """

    model_config = ConfigDict(extra="forbid")

    v: int = ARRANGEMENT_SCHEMA_VERSION
    sessions: Dict[str, TerminalLayoutEntry] = Field(default_factory=dict)

    @field_validator("sessions")
    @classmethod
    def _bounded_sessions(cls, value: Dict[str, TerminalLayoutEntry]) -> Dict[str, TerminalLayoutEntry]:
        if len(value) > MAX_TERMINAL_LAYOUTS:
            raise ValueError(f"at most {MAX_TERMINAL_LAYOUTS} session layouts")
        for key in value:
            if not key or len(key) > MAX_KEY_LENGTH:
                raise ValueError("a session layout key must be 1 to 128 characters")
        return value


def _bounded_home_grid(value: Dict[str, Any]) -> Dict[str, Any]:
    version = value.get("v")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("a home layout carries an integer 'v'")
    if len(json.dumps(value).encode("utf-8")) > MAX_LAYOUT_BYTES:
        raise ValueError("a home layout is too large to store")
    rows = value.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("a home layout carries a non-empty 'rows' list")
    return value


class HomeBoard(BaseModel):
    """One named Home board: an id, a name and its grid.

    Attributes:
      id (str): 1 to 32 of letters, digits, ``_`` and ``-``; unique in the list.
      name (str): 1 to ``MAX_HOME_BOARD_NAME`` characters.
      layout (dict): the board's grid, see ``_bounded_home_grid``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=HOME_BOARD_ID_RE.pattern)
    name: str = Field(min_length=1, max_length=MAX_HOME_BOARD_NAME)
    layout: Dict[str, Any]

    @field_validator("layout")
    @classmethod
    def _bounded_layout(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _bounded_home_grid(value)


class HomeLayout(BaseModel):
    """The Home page's boards, shared by every browser.

    COMPATIBLE WITH THE SINGLE GRID VALUE: ``{v: 1, layout, analytics_seed}``
    (what every earlier browser wrote and read) is accepted and stored as one
    board, ``home``, so nobody's Home changes.

    Attributes:
      v (int): the envelope version (2 with boards).
      boards (list): 1 to ``MAX_HOME_BOARDS`` boards, ids unique.
      analytics_seed (int): how far the default analytics charts were seeded
        (0 to ``MAX_ANALYTICS_SEED``). It lives here, not in a per device
        marker, so a second browser never re-seeds a chart removed on the
        first.
      active (str | None): the id of the active dashboard (the home
        screen); it must name a board in the list. None is absent and is
        never written out.
    """

    model_config = ConfigDict(extra="forbid")

    v: int = 2
    boards: List[HomeBoard] = Field(min_length=1, max_length=MAX_HOME_BOARDS)
    analytics_seed: int = Field(default=0, ge=0, le=MAX_ANALYTICS_SEED)
    active: Optional[str] = Field(default=None, pattern=HOME_BOARD_ID_RE.pattern)

    @model_validator(mode="before")
    @classmethod
    def _from_single_grid(cls, data: Any) -> Any:
        if isinstance(data, dict) and "layout" in data and "boards" not in data and set(data) <= {"v", "layout", "analytics_seed"}:
            converted: Dict[str, Any] = {"v": 2, "boards": [{"id": "home", "name": "home", "layout": data["layout"]}]}
            if "analytics_seed" in data:
                converted["analytics_seed"] = data["analytics_seed"]
            return converted
        return data

    @field_validator("boards")
    @classmethod
    def _unique_ids(cls, value: List[HomeBoard]) -> List[HomeBoard]:
        if len({board.id for board in value}) != len(value):
            raise ValueError("board ids must be unique")
        return value

    @model_validator(mode="after")
    def _active_names_a_board(self) -> "HomeLayout":
        if self.active is not None and all(board.id != self.active for board in self.boards):
            raise ValueError("the active dashboard must be one of the boards")
        return self

    @model_serializer(mode="wrap")
    def _omit_absent_active(self, handler: Any) -> Dict[str, Any]:
        data = handler(self)
        if data.get("active") is None:
            data.pop("active", None)
        return data


class WarroomLayout(BaseModel):
    """The war room page's grid, shared by every browser.

    Attributes:
      v (int): the envelope version (1).
      layout (dict): the page's grid, see ``_bounded_home_grid``.
    """

    model_config = ConfigDict(extra="forbid")

    v: int = 1
    layout: Dict[str, Any]

    @field_validator("layout")
    @classmethod
    def _bounded_layout(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _bounded_home_grid(value)


class UiPreferenceValues(BaseModel):
    """Every preference this server understands, all of them optional.
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
    sidebar_show_open: Optional[StrictBool] = None
    sidebar_show_open_mobile: Optional[StrictBool] = None
    sidebar_show_sleeping: Optional[StrictBool] = None
    sidebar_show_sleeping_mobile: Optional[StrictBool] = None
    sidebar_show_closed: Optional[StrictBool] = None
    sidebar_show_closed_mobile: Optional[StrictBool] = None
    sidebar_list_open: Optional[StrictBool] = None
    sidebar_list_open_mobile: Optional[StrictBool] = None
    sidebar_list_sleeping: Optional[StrictBool] = None
    sidebar_list_sleeping_mobile: Optional[StrictBool] = None
    sidebar_hide_empty_sections: Optional[StrictBool] = None
    menu_order: Optional[List[str]] = None
    sidebar_arrangement: Optional[SidebarArrangement] = None
    sidebar_pinned: Optional[bool] = None
    config_editor_pinned: Optional[bool] = None
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
    warez_modem_sound: Optional[StrictBool] = None
    warez_last_call: Optional[str] = None
    warez_elite_seen: Optional[StrictBool] = None
    install_report_notice_seen: Optional[StrictBool] = None
    waiting_kinds: Optional[AttentionKindsChoice] = None
    bell_kinds: Optional[AttentionKindsChoice] = None
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

    @field_validator("drawer_arrangement")
    @classmethod
    def _drawer_arrangement_size(cls, value: Optional[DrawerArrangement]) -> Optional[DrawerArrangement]:
        if value is None:
            return None
        if len(json.dumps(value.model_dump(mode="json")).encode("utf-8")) > MAX_DRAWER_ARRANGEMENT_BYTES:
            raise ValueError("drawer_arrangement is too large to store")
        return value

    @field_validator("terminal_layouts")
    @classmethod
    def _terminal_layouts_size(cls, value: Optional[TerminalLayouts]) -> Optional[TerminalLayouts]:
        if value is None:
            return None
        if len(json.dumps(value.model_dump(mode="json")).encode("utf-8")) > MAX_TERMINAL_LAYOUTS_BYTES:
            raise ValueError("terminal_layouts is too large to store")
        return value

    @field_validator("home_layout")
    @classmethod
    def _home_layout_size(cls, value: Optional[HomeLayout]) -> Optional[HomeLayout]:
        if value is None:
            return None
        if len(json.dumps(value.model_dump(mode="json")).encode("utf-8")) > MAX_HOME_LAYOUT_BYTES:
            raise ValueError("home_layout is too large to store")
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


def known_fields() -> frozenset:
    return frozenset(UiPreferenceValues.model_fields.keys())


def is_secret_name(name: str) -> bool:
    return name in _SECRET_KEY_NAMES or bool(_SECRET_KEY_SHAPE.search(name))


def empty_block() -> Dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "revision": 0, "values": {}}


def read_block(config: Dict[str, Any]) -> Dict[str, Any]:
    block = config.get(UI_PREFERENCES_KEY)
    if not isinstance(block, dict):
        return empty_block()

    revision = block.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        revision = 0

    version = block.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        version = SCHEMA_VERSION

    values = block.get("values")
    if not isinstance(values, dict):
        values = {}

    return {
        "schema_version": version,
        "revision": revision,
        "values": migrate_retired_placements({k: v for k, v in values.items() if k not in RETIRED_FIELDS}),
    }


def revision_of(config: Dict[str, Any]) -> int:
    return read_block(config)["revision"]


def validate_changes(changes: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(changes, dict):
        raise ValueError("preferences must be sent as an object of field names")
    if not changes:
        raise ValueError("no preference fields were sent")

    known = known_fields()
    typed: Dict[str, Any] = {}
    unknown: Dict[str, Any] = {}

    for name, value in changes.items():
        if not isinstance(name, str) or not name:
            raise ValueError("a preference name must be a non-empty string")
        if is_secret_name(name):
            raise ValueError("that preference name is reserved and cannot be stored")
        if name in RETIRED_FIELDS:
            continue
        if name in known:
            typed[name] = value
        else:
            if len(name) > MAX_KEY_LENGTH:
                raise ValueError("a preference name may be at most 128 characters")
            unknown[name] = value

    if len(unknown) > MAX_UNKNOWN_FIELDS:
        raise ValueError(f"at most {MAX_UNKNOWN_FIELDS} unrecognised preferences at once")

    normalised: Dict[str, Any] = {}
    typed = migrate_retired_placements(typed)
    if typed:
        try:
            model = UiPreferenceValues(**typed)
        except ValidationError as exc:
            raise ValueError(_plain_validation_message(exc)) from exc
        dumped = model.model_dump(mode="json")
        for name in typed:
            normalised[name] = dumped[name]
        _forget_absent_carried(typed, normalised)

    for name, value in unknown.items():
        _refuse_oversized_unknown(name, value)
        normalised[name] = value

    return normalised


_CARRIED_DRAWER_KEYS = ("mobile", "sections")
CARRIED_DRAWER_KEYS = _CARRIED_DRAWER_KEYS


def _forget_absent_carried(typed: Dict[str, Any], normalised: Dict[str, Any]) -> None:
    raw = typed.get("drawer_arrangement")
    value = normalised.get("drawer_arrangement")
    if isinstance(raw, dict) and isinstance(value, dict):
        for key in _CARRIED_DRAWER_KEYS:
            if key not in raw:
                value.pop(key, None)


def _plain_validation_message(exc: ValidationError) -> str:
    parts: List[str] = []
    seen: set = set()
    for error in exc.errors():
        loc = error.get("loc") or ()
        field = str(loc[0]) if loc else "value"
        if field in seen:
            continue
        seen.add(field)
        message = str(error.get("msg") or "invalid value")
        prefix = "Value error, "
        if message.startswith(prefix):
            message = message[len(prefix):]
        parts.append(f"{field}: {message}")
    return "; ".join(parts) if parts else "one or more settings were invalid"


def _refuse_oversized_unknown(name: str, value: Any) -> None:
    import json

    try:
        encoded = json.dumps(value)
    except (TypeError, ValueError):
        raise ValueError(f"preference '{name}' is not a storable value")
    if len(encoded.encode("utf-8")) > MAX_UNKNOWN_VALUE_BYTES:
        raise ValueError(f"preference '{name}' is too large to store")


def apply_changes(
    config: Dict[str, Any], changes: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    block = read_block(config)
    values = dict(block["values"])
    moved: Dict[str, Any] = {}

    for name, value in changes.items():
        if value is None:
            if name in values:
                values.pop(name)
                moved[name] = None
            continue
        value = _carry_absent(values.get(name), name, value)
        if values.get(name, _MISSING) != value:
            values[name] = value
            moved[name] = value

    if not moved:
        return config, block, {}

    new_block = {
        "schema_version": SCHEMA_VERSION,
        "revision": block["revision"] + 1,
        "values": values,
    }
    new_config = dict(config)
    new_config[UI_PREFERENCES_KEY] = new_block
    return new_config, new_block, moved


def _carry_absent(stored: Any, name: str, incoming: Any) -> Any:
    if name != "drawer_arrangement" or not isinstance(incoming, dict) or not isinstance(stored, dict):
        return incoming
    carried = {
        key: stored[key]
        for key in _CARRIED_DRAWER_KEYS
        if key not in incoming and stored.get(key) is not None
    }
    return {**incoming, **carried} if carried else incoming


class _Missing:

    def __repr__(self) -> str:
        return "<missing>"


_MISSING = _Missing()

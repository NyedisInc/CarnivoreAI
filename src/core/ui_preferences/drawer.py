
from __future__ import annotations

import re
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.widget_placement.glance import GlancePlacement, OptionValue, check_option_values, check_placements
from src.core.ui_preferences.constants import ARRANGEMENT_SCHEMA_VERSION, DRAWER_ZONE_INSTANCE_RE, DRAWER_ZONE_LOOKS, DRAWER_ZONE_TARGET_RE, DRAWER_ZONE_VIEW_RE, DRAWER_ZONE_WIDGET_ID_RE, MAX_DRAWER_ZONE_ITEMS, MAX_DRAWER_ZONE_ITEM_OPTIONS, MAX_FOLDED_SECTIONS, MAX_FOLDS, MAX_KEY_LENGTH, MAX_REMEMBERED, MAX_SESSION_RAIL_ITEMS, MAX_SESSION_RAIL_SECTIONS, SESSION_RAIL_RATIO_MAX, SESSION_RAIL_RATIO_MIN
from src.core.ui_preferences.checks import unique_placements


_RESERVED_FOLD_KEYS = frozenset(
    {"pinned", "other", "rogue", "terminals", "browsers", "files", "review", "ledger_hidden", "ledger_expanded",
     "ledger_glance", "layouts", "companies", "groups", "pack", "open", "sleeping"}
)

SECTION_IDS = ("pinned", "layouts", "groups", "companies", "rogue", "terminals", "browsers", "review", "pack")

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
    """One device class's VIEW of the drawer (Alex (example-owner), 2026-10-10).

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

    Alex (Adoom666), 2026-09-26: "pins should not be per device." Keyed by
    ``session_uuid``, never by tmux name, because a name is reused and
    changes on a reopen (CLAUDE.md, "a tmux name is not a session's identity
    in the sidebar"). The browser's own localStorage envelope stays its
    render model and offline cache; ``client/js/session-sidebar-sync.js``
    translates between the two.

    Attributes:
      v (int): the envelope version.
      pinned (list[str]): pinned session uuids and ``layout:<uuid>`` saved
        Layout pins (issue #424), one mixed list in pinned-band order.
      order (list[str]): the user's explicit order of the shared band.
      bands (dict): a group, project or kind band key (``g:<uuid>``,
        ``p:<id>``, ``rogue``, ``terminals``, ``browsers``) to that band's own
        top-to-bottom session uuids.
      collapsed (list[str]): folded section keys, validated by SHAPE as the
        client does, never against a live group list. ``layouts`` folds the
        LAYOUTS section (issue #424); it is a fold key only, never a band.
        ``layout:<uuid>`` (issue #802) is a PER-LAYOUT fold - whether one
        saved Layout's row is expanded to show its member sessions. It
        reads INVERTED from every other fold key here: since a Layout
        defaults to COLLAPSED (unlike every other section, which defaults
        open), the client stores PRESENCE to mean "the user expanded this
        one away from its default", not "collapsed" - see
        ``web/src/lib/drawer/layouts-*.ts``'s docblock.
      projects_open (bool | None): the PROJECTS super-heading's fold; None
        means never set here.
      mobile (DrawerViewState | None): the PHONE's view (Alex (example-owner),
        2026-10-10, ``docs/DECISIONS.md``). ``collapsed`` above is the DESKTOP
        fold list, the legacy meaning every older client still reads and
        writes; ``mobile.collapsed`` is the phone's. None means never split:
        the phone shows the desktop list. Pins, order and bands stay one
        shared value. ``apply_changes`` keeps the stored ``mobile`` when an
        incoming value omits the key.
      sections (list[str] | None): the user's order of the drawer's top-level
        sections, ids from ``SECTION_IDS``, no repeats (Alex (Adoom666),
        2026-10-12, #1687). ONE value for every device. None means the default
        order, which is code; a section a stored list lacks joins at its default
        slot on the client. ``apply_changes`` keeps the stored list when an
        incoming value omits the key; an explicit null clears it.
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

    Attributes:
      agents (bool | None): the sub-agent people icon. None = use this
        density's default (see ``DRAWER_ROW_ICON_DEFAULTS``), never False.
      shells (bool | None): the background-shell terminal icon.
      timers (bool | None): the live-timer clock icon.
      cup (bool | None): the keep-awake coffee cup. None = shown (see
        ``DRAWER_ROW_EXTRA_ICON_DEFAULT``). Hiding it never hides the
        keep-awake STATE: the row menu still offers "keep awake" and, while
        a hidden cup would have shown, the row's name tooltip mentions it
        (Joe (ccsliinc), 2026-09-28: "for the people who want it super
        clean").
      pin (bool | None): the pin toggle. None = shown. Hiding it never
        changes SORTING - a pinned row still sorts pinned - and pinning
        stays reachable from the row menu.
      context (bool | None): the context gauge, a thin fill along the row's
        bottom edge (issue #1102). None = shown (see
        ``DRAWER_ROW_CONTEXT_GAUGE_DEFAULT``); a row with no measured
        context draws nothing either way.
      automations (bool | None): the Carnivore timers icon, a session's
        automations (Task Manager item 454). None = shown (see
        ``DRAWER_ROW_AUTOMATIONS_DEFAULT``) on a session that has any; an
        explicit False hides it.
      menu (bool | None): the kebab trigger. None = shown. Hiding it never
        hides the green update-ready icon, which draws in the kebab's slot
        regardless of this setting, and never removes the row's other ways
        to open its menu: right click, long press/touch, and Shift+F10 (or
        the keyboard menu key) on a focused row. A faint kebab still
        appears on hover so a mouse user can find it.

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

    Joe (ccsliinc), 2026-09-28, issue #1061: a dedicated settings-screen
    control (built by another worker) writes this; the drawer rows
    (``web/src/lib/sidebar-shell/row-chips.ts``, the only row renderer)
    read it live through the same
    ``ui_preferences`` sync every other shared preference here follows -
    ABSENT IS NOT A DEFAULT for the FIELD as a whole (the whole block
    missing means "never set anywhere, use every built-in default"), but
    each density's THREE booleans individually default per
    ``DRAWER_ROW_ICON_DEFAULTS`` when that density's own sub-object, or an
    individual key in it, is missing - a user who only unhides `agents` in
    compact must not silently reset `shells`/`timers` back to shown.
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

    Joe (ccsliinc), 2026-09-29: "the providers area on left column should be
    a widget area that i can drag in other widgets to." The area used to be
    the fixed provider ledger panel. ABSENT (the whole field) MEANS THE
    DEFAULT, ``[core.ledger]``: the server never fabricates it. ``items: []``
    is a real answer (the area emptied on purpose) and stays distinct from
    absent. Shared by every device like ``drawer_arrangement`` (issue #645);
    written by the layout editor, followed live through the preference layer
    (revision, 409 adopt and replay).
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
        unique_placements(value, "the drawer area")
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

    Joe (ccsliinc), 2026-10-09: "rebuild the session view sidebar as a widget
    rail ... changes becomes a widget." The same item shape and rules as the
    drawer's widget area (``DrawerZoneItem``: a widget id, an optional look, a
    family copy's target; each key once ACROSS the whole rail, at most
    ``MAX_SESSION_RAIL_ITEMS``: a rail scrolls, it does not cap), without the
    glance placements. ONE MODEL FOR BOTH RAILS: ``session_rail`` is the side
    rail (ABSENT MEANS THE DEFAULT, files and notes; Alex (Adoom666), 2026-10-11) and
    ``session_rail_bottom`` the bottom one (ABSENT READS AS [core.shell, core.scheduled-tasks], #2511); the server
    never fabricates either. One value for every device; written by the layout
    editor, followed live through the preference layer. The bars' own chrome
    (show, size, auto-hide) is the separate ``widget_bars`` field
    (``WidgetBars``); resetting the bars clears all three fields at once.

    TWO SHAPES, BOTH READ (Joe (ccsliinc), 2026-10-09, the split rail):
      - ``v: 1``, ``items``: the first, flat list. Still valid, and the client
        reads it as ONE section, so no stored rail is ever lost.
      - ``v: 2``, ``sections``: one or two ``SessionRailSection``; ``ratio`` is
        the first section's share of the rail's length, present only with two
        sections, inside ``SESSION_RAIL_RATIO_MIN`` and ``_MAX``. With two
        sections neither may be empty (dragging the last widget out of one
        removes the split). The client writes this shape.
    ``items: []`` (or one empty section) is a real answer (the rail emptied on
    purpose).
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
        unique_placements(flat, "the session rail")
        return self

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

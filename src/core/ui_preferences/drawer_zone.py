
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.widget_placement.glance import GlancePlacement, OptionValue, check_option_values, check_placements
from src.core.ui_preferences.constants import DRAWER_ZONE_INSTANCE_RE, DRAWER_ZONE_LOOKS, DRAWER_ZONE_TARGET_RE, DRAWER_ZONE_VIEW_RE, DRAWER_ZONE_WIDGET_ID_RE, MAX_DRAWER_ZONE_ITEMS, MAX_DRAWER_ZONE_ITEM_OPTIONS, MAX_SESSION_RAIL_ITEMS, MAX_SESSION_RAIL_SECTIONS, MAX_SESSION_RAIL_V2_SECTIONS, SESSION_RAIL_CUT_EPSILON, SESSION_RAIL_MIN_SHARE, SESSION_RAIL_RATIO_MAX, SESSION_RAIL_RATIO_MIN
from src.core.ui_preferences.checks import unique_placements


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


def _check_cuts(cuts: List[float], sections: int) -> None:
    if len(cuts) != sections - 1:
        raise ValueError("a v3 session rail has one cut fewer than it has sections")
    edges = [0.0, *cuts, 1.0]
    for low, high in zip(edges, edges[1:]):
        if high - low < SESSION_RAIL_MIN_SHARE - SESSION_RAIL_CUT_EPSILON:
            raise ValueError(f"every area of a session rail takes at least {SESSION_RAIL_MIN_SHARE} of its length, in order")
    if any(not 0.0 < cut < 1.0 for cut in cuts):
        raise ValueError("a session rail cut is strictly between 0 and 1")


class SessionRail(BaseModel):
    """The session view's widget rail: an ORDERED list of widget instances, in one to four sections (issues #1472, #2766).

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

    THREE SHAPES, ALL READ:
      - ``v: 1``, ``items``: the first, flat list. Still valid, and the client
        reads it as ONE section, so no stored rail is ever lost.
      - ``v: 2``, ``sections``: one or two ``SessionRailSection``; ``ratio`` is
        the first section's share of the rail's length, present only with two
        sections, inside ``SESSION_RAIL_RATIO_MIN`` and ``_MAX``. With two
        sections neither may be empty (dragging the last widget out of one
        removes the split). The client writes this shape for at most two areas,
        so an app that only knows v2 keeps reading it.
      - ``v: 3``, ``sections`` and ``cuts`` (Joe (ccsliinc), 2026-11-02, #2766):
        up to ``MAX_SESSION_RAIL_SECTIONS`` sections, ``cuts`` the seams as
        sorted fractions strictly inside 0..1, one fewer than the sections, no
        area under ``SESSION_RAIL_MIN_SHARE``. With more than one section none
        may be empty. The client writes this shape only for three or more areas.
    ``items: []`` (or one empty section) is a real answer (the rail emptied on
    purpose). ``cuts_as_v3`` reads any shape as v3's list of cuts.
    """

    model_config = ConfigDict(extra="forbid")

    v: int = 1
    items: Optional[List[DrawerZoneItem]] = None
    sections: Optional[List[SessionRailSection]] = None
    ratio: Optional[float] = None
    cuts: Optional[List[float]] = None

    def cuts_as_v3(self) -> List[float]:
        if self.v == 3:
            return list(self.cuts or [])
        if self.v == 2 and self.ratio is not None:
            return [float(self.ratio)]
        return []

    def _check_v2(self) -> List[DrawerZoneItem]:
        if self.items is not None or self.sections is None or self.cuts is not None:
            raise ValueError("a v2 session rail holds sections, not items or cuts")
        if not 1 <= len(self.sections) <= MAX_SESSION_RAIL_V2_SECTIONS:
            raise ValueError(f"a v2 session rail has 1 to {MAX_SESSION_RAIL_V2_SECTIONS} sections; more is v3")
        split = len(self.sections) == 2
        if split and any(not section.items for section in self.sections):
            raise ValueError("a split session rail has widgets in both sections")
        if (self.ratio is not None) != split:
            raise ValueError("a session rail carries a ratio exactly when it is split")
        if split and not SESSION_RAIL_RATIO_MIN <= float(self.ratio) <= SESSION_RAIL_RATIO_MAX:
            raise ValueError(f"the split ratio is between {SESSION_RAIL_RATIO_MIN} and {SESSION_RAIL_RATIO_MAX}")
        return [item for section in self.sections for item in section.items]

    def _check_v3(self) -> List[DrawerZoneItem]:
        if self.items is not None or self.ratio is not None or self.sections is None or self.cuts is None:
            raise ValueError("a v3 session rail holds sections and cuts, not items or a ratio")
        if not 1 <= len(self.sections) <= MAX_SESSION_RAIL_SECTIONS:
            raise ValueError(f"a session rail has 1 to {MAX_SESSION_RAIL_SECTIONS} sections")
        if len(self.sections) > 1 and any(not section.items for section in self.sections):
            raise ValueError("a split session rail has widgets in every section")
        _check_cuts(self.cuts, len(self.sections))
        return [item for section in self.sections for item in section.items]

    @model_validator(mode="after")
    def _shape(self) -> "SessionRail":
        if self.v == 1:
            if self.sections is not None or self.ratio is not None or self.cuts is not None:
                raise ValueError("a v1 session rail is a flat list: items only")
            if self.items is None:
                self.items = []
            flat = list(self.items)
        elif self.v == 2:
            flat = self._check_v2()
        elif self.v == 3:
            flat = self._check_v3()
        else:
            raise ValueError("a session rail is version 1, 2 or 3")
        if len(flat) > MAX_SESSION_RAIL_ITEMS:
            raise ValueError(f"at most {MAX_SESSION_RAIL_ITEMS} session rail widgets")
        unique_placements(flat, "the session rail")
        return self

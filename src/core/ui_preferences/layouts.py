
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from src.core.ui_preferences.constants import ARRANGEMENT_SCHEMA_VERSION, FOOT_BAR_LAYOUT_OPTIONS, HOME_BOARD_ID_RE, MAX_ANALYTICS_SEED, MAX_HOME_BOARDS, MAX_HOME_BOARD_NAME, MAX_KEY_LENGTH, MAX_TABS_PER_GROUP, MAX_TAB_GROUPS, MAX_TERMINAL_LAYOUTS, PAGE_TAB_ID_RE, TAB_ID_RE, WIDGET_TAB_ID_RE
from src.core.ui_preferences.checks import check_grid


class FootBarLayout(BaseModel):
    """Which built layout each half of the terminal foot bar draws.

    Attributes:
      collapsed (str | None): 'a' (meters first), 'b' (a status line
        grouped by scope) or 'c' (attention first). None = 'a'.
      open (str | None): 'a' (band + three columns), 'b' (a tabs rail) or
        'c' (one list grouped by owner). None = 'a'.

    Issue #1053, Joe (ccsliinc), 2026-09-28: "you gave me options before
    for the small and open area. make them all and let it be an option."
    Both halves independently default to 'a' when absent, so nobody's bar
    changes layout until they pick one from the settings picker
    (``web/src/lib/settings-page/FootBarItemsPanel.svelte``).
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
        return check_grid(value, "terminal layout", allow_tree=True)

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

    Owner, 2026-09-25 (issue #451): "Arrangement persisted server side via
    ui_preferences, synced across devices." Keyed by the SAME key the
    browser stores a session's grid under (``session-layouts.ts::layoutKey``,
    tmux name plus ``#{session_created}``), so a new session reusing a dead
    one's name never inherits it. WHICH TAB A COMPONENT SHOWS IS NOT HERE:
    that is per device by the owner's ruling and stays in the browser.

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
        return check_grid(value, "home layout")


class HomeLayout(BaseModel):
    """The Home page's boards, shared by every browser.

    Alex (Adoom666), 2026-09-29: "the layout of the home page and analytics
    settings stay the same between browsers", and (same day) several named
    boards, switched from the edit layout drawer. ABSENT (the whole field)
    means no browser has written one yet; the server never fabricates it. The
    browser migrates its own stored grid up once, then follows this value
    like ``terminal_layouts`` (revision, 409 adopt and replay once).

    DASHBOARDS (Joe (ccsliinc), 2026-10-02, ``docs/dashboards.md``): every
    board is a dashboard, and ``active`` names the one that IS the home
    screen, the same on every browser. ABSENT means no browser has chosen
    yet: each one keeps the board it already showed (the old per device
    pick) and the first write records it, so nothing changes on upgrade.

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

    Alex (Adoom666), 2026-10-20, SUPERPLAN for #135: the war room is an editable layout page whose widgets
    can be dropped like Home's. ONE grid (no boards). ABSENT (the whole field) means no browser has written
    one yet; the server never fabricates it, and the browser keeps its default until it saves.

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
        return check_grid(value, "home layout")

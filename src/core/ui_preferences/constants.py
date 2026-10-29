
from __future__ import annotations

import re


from src.core import theme_script_consent


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
"""``compact`` is Alex (example-owner)'s toast behaviour and the default; ``detailed``
is Joe (ccsliinc)'s mode (issue #750). See ``docs/notifications.md``."""
LAUNCHPAD_SECTION_IDS = ("running-sessions", "recent-sessions", "recent-projects")

FOOT_BAR_ITEM_IDS = (
    "model", "effort", "context", "window_5h", "window_7d", "agents", "shells", "timers",
)
"""The eight items the collapsed terminal foot bar can show or hide (issue
#1053), mirrored client side in
``FOOT_BAR_ITEM_IDS``. The two lists must stay identical: a server id this
client build has never heard of would validate and then never be settable
from the one control that writes this field."""

FOOT_BAR_ORDER_IDS = ("context", "window_5h", "window_7d")
"""The three meters of the collapsed status bar whose left-to-right order the
user may choose (Joe (ccsliinc), 2026-09-29), mirrored client side in
``FOOT_BAR_ORDER_IDS``. The model stays leftmost (a standing ruling) and the
work segments stay on the right, so neither is orderable."""

RETIRED_FIELDS = (
    "header_quicklinks", "automations_show_huddle", "crosstalk_cards_sent", "crosstalk_cards_received", "wake_on_click",
    "sidebar_show_colors", "sidebar_show_colors_mobile",
    "sidebar_arrangement", "config_editor_pinned", "warez_modem_sound", "install_report_notice_seen",
    "sidebar_show_open", "sidebar_show_open_mobile", "sidebar_show_sleeping", "sidebar_show_sleeping_mobile", "bell_kinds",
)
"""Preference names this build no longer owns. A stored document may still
carry them (an install from before the retirement, a peer or a stale browser
tab that still PATCHes one): ``read_block`` never exposes them, so the next
committed write drops them from disk, and ``validate_changes`` ignores them
instead of keeping them as unrecognised fields. ``header_quicklinks`` came
from #1065 (Joe (ccsliinc), 2026-09-28) and was retired by #1285 (Alex
(Adoom666), 2026-10-03: "delete the dead header_quicklinks field too"). ``automations_show_huddle``
was the Automations page's opt-in task manager tab switch (#1490, 2026-10-09), retired the same day: the tab now follows the
task manager plugin's own enablement (``docs/automations.md``). ``crosstalk_cards_sent`` and ``crosstalk_cards_received``
were the two switches of the terminal crosstalk card (Joe (ccsliinc), 2026-10-11), retired the same day when the card and its
scanner were deleted (Alex (Adoom666), 2026-10-11, ``docs/DECISIONS.md``); an install that stored them keeps working and the
next committed write drops them. ``wake_on_click`` (#730, Joe (ccsliinc), 2026-09-26) was the opt-in to wake an asleep row
straight from a click; Alex (Adoom666), 2026-10-12, "it doesn't do anything", removed it: a click on an asleep row now always
arms the row's wake button (#1505), which is what an install that never stored it already saw. ``sidebar_show_colors`` and
``sidebar_show_colors_mobile`` (the drawer's "show colors" tick, Joe (ccsliinc), 2026-10-11) went with Alex (example-owner),
2026-10-12, "remove the "show colors" menu item": a set color is always drawn now, so an install that stored ``false`` sees
its group, layout and company colors again. ``sidebar_arrangement`` (superseded 2026-09-26 by ``drawer_arrangement``, #645),
``config_editor_pinned`` (the file drawer's pin, removed 2026-09-23), ``warez_modem_sound`` (the Elite Access sound option,
removed Alex (Adoom666), 2026-10-18), ``install_report_notice_seen`` (the install notice modal, removed the same day),
``sidebar_show_open`` and ``sidebar_show_sleeping`` with their ``_mobile`` twins (the #1766 section toggles, replaced by
``sidebar_list_open`` and ``sidebar_list_sleeping``) and ``bell_kinds`` (the top bell is unfiltered; the choice lives in
``waiting_kinds``) were typed fields kept so stored files loaded; nothing reads them, so they retire here with the rest."""

FOOT_BAR_LAYOUT_OPTIONS = ("a", "b", "c")
"""The three built layouts each half of the terminal foot bar can take
(issue #1053, Joe (ccsliinc), 2026-09-28: "make them all and let it be an
option"), mirrored client side by `FOOT_BAR_COLLAPSED_OPTIONS`
(`web/src/opscenter/cells/terminal-live/foot-plan.ts`) and
`SESSION_CONTROL_OPTIONS` (`web/src/lib/session-control/control-center.ts`).
`'a'` is the default for both halves."""

THEME_ID_RE = theme_script_consent.THEME_ID_RE
"""IMPORTED, NEVER RESTATED. This file carried its own copy of the pattern
until 2026-09-10, and the two answered the same question: a theme id has to
be spellable BOTH as a consent key and as the selected theme, so a folder
name one accepted and the other refused is a theme the user can select and
cannot record a decision about, or the reverse. Two definitions of one rule
are two rules the moment somebody widens one of them."""

MODEL_ID_RE = re.compile(r"^(?!-)[A-Za-z0-9._~/-]{1,120}$")
"""Mirrors ``providers.js``'s client-side check and the server's own
``MODEL_ID_PATTERN``. An empty string is legal and means "claude, no
OpenRouter model", which is what the client already stores."""

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
"""The whole field serialised. It rides every ``preferences.changed`` frame,
which the event socket bounds at 1 MiB, so it stays well under that."""
MAX_HOME_LAYOUT_BYTES = 262144
"""The whole ``home_layout`` field serialised: up to ``MAX_HOME_BOARDS`` grids
(each capped at ``MAX_LAYOUT_BYTES``, so 192 KiB at most) plus names and ids.
Raised from 32 KiB when Home gained boards (Alex (Adoom666), 2026-09-29); it
matches ``MAX_TERMINAL_LAYOUTS_BYTES`` and stays well under the 1 MiB the
event socket bounds a ``preferences.changed`` frame at."""
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
"""A widget tab id (``web/src/opscenter/engine/widget-tabs.ts``, issue #2008 slice 8b): ``widget:`` and a
widget manifest id such as ``core.tasks``. A TAB may be one; a group SLOT never is. Approved by Joe (ccsliinc),
Task Manager item 1049, message 5669, 2026-10-19 (``docs/DECISIONS.md``)."""
MAX_UNKNOWN_FIELDS = 64
MAX_KEY_LENGTH = 128
MAX_MENU_ORDER = 64
MAX_UNKNOWN_VALUE_BYTES = 8192

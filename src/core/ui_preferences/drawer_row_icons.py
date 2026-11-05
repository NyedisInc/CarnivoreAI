
from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict


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

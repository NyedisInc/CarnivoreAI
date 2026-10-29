
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra
from src.core.mcp.common import ToolError

OWNER_ONLY_FIELDS = frozenset({"theme_script_consent", "disabled_plugins", "desktop_terminal_app", "desktop_terminal_custom"})


def _update(call: ra.Call) -> Any:
    from src.api.preferences_routes import PreferencesUpdateRequest

    changes = call.args["changes"]
    if not isinstance(changes, dict) or not changes:
        raise ToolError("changes is required: an object of preference name to new value (null unsets one)")
    refused = sorted(OWNER_ONLY_FIELDS & set(changes))
    if refused:
        raise ToolError(f"{', '.join(refused)} can only be changed by the owner in the app")
    return call.route(call.request, PreferencesUpdateRequest(changes=changes,
                                                             expected_revision=call.args.get("expected_revision")))


SPECS = (
    ra.RouteTool(
        name="preferences_get", route="src.api.preferences_routes:get_preferences", gate=ra.READ,
        description="The owner's synced UI preferences (the global theme, drawer, toasts, layouts, home dashboards and "
                    "the rest) with the revision preferences_update sends back.",
        invoke=lambda call: call.route(call.request),
    ),
    ra.RouteTool(
        name="preferences_update", route="src.api.preferences_routes:update_preferences", gate=ra.ARRANGE,
        description="Change synced UI preferences: changes maps a preference name to its new value (null returns "
                    "it to the default), for example {\"theme\": \"matrix\"} or {\"time_zone\": \"Europe/Paris\"} (IANA name; "
                    "null is America/New_York). Send preferences_get's revision as expected_revision "
                    "to refuse a stale write. theme_script_consent, disabled_plugins, desktop_terminal_app and desktop_terminal_custom stay the owner's.",
        properties={"changes": {"type": "object"}, "expected_revision": {"type": "integer", "minimum": 0}},
        required=("changes",), invoke=_update, example={"changes": {"toast_mode": "detailed"}, "expected_revision": 3},
    ),
    ra.RouteTool(
        name="widget_bars_reset", route="src.api.widget_bars_routes:reset_widget_bars", gate=ra.ARRANGE,
        description="Put both widget bars (the session view's right and bottom bars) back to their defaults: shown, "
                    "cozy, auto-hidden, both at once, and the default widgets in each. Clears widget_bars, session_rail "
                    "and session_rail_bottom in one write; every open browser follows live. Answers committed or, "
                    "when nothing was customized, unchanged.",
        invoke=lambda call: call.route(call.request),
    ),
    ra.RouteTool(
        name="themes_list", route="src.api.themes_routes:list_themes", gate=ra.READ,
        description="Every installed theme (bundled and user): id, name, source and colors. Pick one for "
                    "session_theme_set. The global theme is the owner's setting in the app (preferences_update needs "
                    "the owner to tick app settings tools).",
        invoke=lambda call: call.route(call.request),
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)

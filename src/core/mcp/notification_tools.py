
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra


async def _settings(call: ra.Call) -> Any:
    body = dict(await call.route(call.request))
    body.pop("destinations", None)
    body["destinations_tool"] = "notification_destinations_list"
    return body


async def _pause(call: ra.Call) -> Any:
    from src.api.notification_settings_routes import PauseBody

    body = dict(await call.route(PauseBody(paused=call.args["paused"]), call.request))
    body.pop("destinations", None)
    return body


def _snooze(call: ra.Call) -> Any:
    from src.api.app_alerts_routes import SnoozeBody

    return call.route(call.args["alert_id"], SnoozeBody(minutes=call.args["minutes"]))


def _open_settings(call: ra.Call) -> Any:
    from src.api.app_alerts_routes import SystemSettingsBody

    return call.route(SystemSettingsBody(pane=call.args["pane"]))


SPECS = (
    ra.RouteTool(
        name="notification_settings_get", route="src.api.notification_settings_routes:get_settings", gate=ra.READ,
        description="Notification settings: the pause switch, per-type defaults, the screen column and every "
                    "destination's ticks, plus sync state (destinations themselves: notification_destinations_list).",
        invoke=_settings,
    ),
    ra.RouteTool(
        name="notification_pause_set", route="src.api.notification_settings_routes:put_settings", gate=ra.ARRANGE,
        description="Pause (paused true) or resume every notification from this computer. Local only, never synced.",
        properties={"paused": {"type": "boolean"}}, required=("paused",), invoke=_pause, example={"paused": True},
    ),
    ra.RouteTool(
        name="alert_dismiss", route="src.api.app_alerts_routes:dismiss", gate=ra.ARRANGE,
        description="Dismiss one app alert (id from alerts_list).",
        properties={"alert_id": {"type": "integer"}}, required=("alert_id",),
        invoke=lambda call: call.route(call.args["alert_id"]), example={"alert_id": 7},
    ),
    ra.RouteTool(
        name="alert_snooze", route="src.api.app_alerts_routes:snooze", gate=ra.ARRANGE,
        description="Snooze one open app alert for minutes (id from alerts_list).",
        properties={"alert_id": {"type": "integer"}, "minutes": {"type": "integer", "minimum": 1}},
        required=("alert_id", "minutes"), invoke=_snooze, example={"alert_id": 7, "minutes": 60},
    ),
    ra.RouteTool(
        name="alert_check", route="src.api.app_alerts_routes:recheck_alert", gate=ra.ARRANGE,
        description="Run the check behind one app alert again now (alerts_list shows a recheck action on the ones that "
                    "support it); the alert resolves itself if the fault cleared. Answers the alert as it stands.",
        properties={"alert_id": {"type": "integer"}}, required=("alert_id",),
        invoke=lambda call: call.route(call.args["alert_id"]), example={"alert_id": 7},
    ),
    ra.RouteTool(
        name="alert_open_system_settings", route="src.api.app_alerts_routes:open_system_settings", gate=ra.ARRANGE,
        description="Open one macOS System Settings pane on the Mac running Carnivore (pane: full_disk_access), the "
                    "fix an alert's open_privacy action offers. Changes nothing by itself; the owner grants access there.",
        properties={"pane": {"type": "string", "enum": ["full_disk_access"]}}, required=("pane",),
        invoke=_open_settings, example={"pane": "full_disk_access"},
    ),
    ra.RouteTool(
        name="alerts_dismiss_resolved", route="src.api.app_alerts_routes:dismiss_resolved", gate=ra.ARRANGE,
        description="Dismiss every resolved app alert at once.", invoke=lambda call: call.route(),
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)


from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra
from src.core.mcp.common import ToolError

_REV = {"expected_revision": {"type": "integer", "minimum": 0,
                              "description": "the revision dashboards_list returned; omit to skip the check"}}
_ID = {"dashboard_id": {"type": "string"}}
_KIND = {"kind": {"type": "string", "enum": ["widget", "plugin"]}, "item_id": {"type": "string"}}


def _create(call: ra.Call) -> Any:
    from src.api.dashboard_routes import CreateRequest

    fields = {k: call.args[k] for k in ("name", "layout", "copy_of", "expected_revision") if k in call.args}
    return call.route(CreateRequest(**fields), call.request)


def _rename(call: ra.Call) -> Any:
    from src.api.dashboard_routes import RenameRequest

    return call.route(call.args["dashboard_id"],
                      RenameRequest(name=call.args["name"], expected_revision=call.args.get("expected_revision")),
                      call.request)


def _layout(call: ra.Call) -> Any:
    from src.api.dashboard_routes import LayoutRequest

    return call.route(call.args["dashboard_id"],
                      LayoutRequest(layout=call.args["layout"], expected_revision=call.args.get("expected_revision")),
                      call.request)


def _activate(call: ra.Call) -> Any:
    from src.api.dashboard_routes import ActivateRequest

    return call.route(call.args["dashboard_id"], call.request,
                      ActivateRequest(expected_revision=call.args.get("expected_revision")))


def _item_patch(call: ra.Call) -> Any:
    from src.models.item_settings import ItemSettingsPatch

    if call.args["kind"] != "widget":
        raise ToolError("item_settings_update changes widget settings only; a plugin's settings are the owner's, in the app")
    fields = {k: call.args[k] for k in ("values", "enabled", "expected_revision") if k in call.args}
    return call.route(call.request, call.args["kind"], call.args["item_id"], ItemSettingsPatch(**fields))


SPECS = (
    ra.RouteTool(
        name="dashboards_list", route="src.api.dashboard_routes:list_dashboards", gate=ra.READ,
        description="Every Home dashboard (id, name), which one is active, and the preference revision writes send back.",
        invoke=lambda call: call.route(call.request),
    ),
    ra.RouteTool(
        name="dashboard_create", route="src.api.dashboard_routes:create_dashboard", gate=ra.ARRANGE,
        description="Add a Home dashboard (it does not become active). Its grid is layout, else a copy of copy_of, else "
                    "of the active dashboard.",
        properties={"name": {"type": "string", "maxLength": 60}, "layout": {"type": "object"},
                    "copy_of": {"type": "string"}, **_REV},
        required=("name",), invoke=_create, example={"name": "ops"},
    ),
    ra.RouteTool(
        name="dashboard_rename", route="src.api.dashboard_routes:rename_dashboard", gate=ra.ARRANGE,
        description="Rename a Home dashboard.", properties={**_ID, "name": {"type": "string", "maxLength": 60}, **_REV},
        required=("dashboard_id", "name"), invoke=_rename, example={"dashboard_id": "b1", "name": "ops"},
    ),
    ra.RouteTool(
        name="dashboard_layout_set", route="src.api.dashboard_routes:set_dashboard_layout", gate=ra.ARRANGE,
        description="Replace one Home dashboard's widget grid (the layout object dashboards and widgets use); every "
                    "other dashboard stays as stored.",
        properties={**_ID, "layout": {"type": "object"}, **_REV}, required=("dashboard_id", "layout"),
        invoke=_layout, example={"dashboard_id": "b1", "layout": {"cells": []}},
    ),
    ra.RouteTool(
        name="dashboard_activate", route="src.api.dashboard_routes:activate_dashboard", gate=ra.ARRANGE,
        description="Make a dashboard the Home screen on every browser.", properties={**_ID, **_REV},
        required=("dashboard_id",), invoke=_activate, example={"dashboard_id": "b1"},
    ),
    ra.RouteTool(
        name="widgets_list", route="src.api.item_settings_routes:list_widgets", gate=ra.READ,
        description="Every widget this build declares: id, instancing, enabled (null for a per-target kind) and "
                    "whether it has settings.",
        invoke=lambda call: call.route(),
    ),
    ra.RouteTool(
        name="item_settings_get", route="src.api.item_settings_routes:get_item", gate=ra.READ,
        description="One widget's or plugin's settings: the stored choices, their schema and the item revision.",
        properties=_KIND, required=("kind", "item_id"),
        invoke=lambda call: call.route(call.args["kind"], call.args["item_id"]),
        example={"kind": "widget", "item_id": "core.activity-log"},
    ),
    ra.RouteTool(
        name="item_settings_update", route="src.api.item_settings_routes:patch_item", gate=ra.ARRANGE,
        description="Change some of one widget's settings (values: key to value, null clears) and/or its "
                    "on/off switch (enabled). Each key is checked against the item's schema; send the item revision "
                    "item_settings_get returned as expected_revision to refuse a stale write.",
        properties={"kind": {"type": "string", "enum": ["widget"]}, "item_id": {"type": "string"}, "values": {"type": "object"}, "enabled": {"type": "boolean"},
                    "expected_revision": {"type": "integer", "minimum": 0}},
        required=("kind", "item_id"), invoke=_item_patch,
        example={"kind": "widget", "item_id": "core.activity-log", "values": {"showSystem": False}},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)


async def dashboard_delete(manager: Any, caller: Any, args: dict) -> dict:
    from src.api import dashboard_routes
    from src.core.mcp.common import _ok
    from src.core.mcp.write_tools import _via_route, park
    from fastapi.encoders import jsonable_encoder

    if set(args) - {"dashboard_id", "expected_revision"} or not isinstance(args.get("dashboard_id"), str):
        raise ToolError("dashboard_delete takes dashboard_id and optionally expected_revision")
    request = ra.route_request(manager)

    async def run(_approved: bool) -> dict:
        answer = await _via_route(dashboard_routes.delete_dashboard(args["dashboard_id"], request, args.get("expected_revision")))
        return _ok(jsonable_encoder(answer))

    summary = f"DELETE Home dashboard {args['dashboard_id']}"
    return await park(manager, caller, "", "", "dashboard_delete", summary, dict(args), run,
                      dedupe_key=f"dashboard_delete:{args['dashboard_id']}")


WRITE_TOOLS["dashboard_delete"] = (
    "Remove a Home dashboard. The active one is refused: activate another first. Always waits for the owner's "
    "approval, even in Beast Mode.",
    {**_ID, **_REV}, ["dashboard_id"], dashboard_delete,
)

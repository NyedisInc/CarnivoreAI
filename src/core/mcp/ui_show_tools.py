
from __future__ import annotations

from src.core.mcp import route_adapters as ra
from src.core.ui_show import KINDS
from src.models.ui_show import MAX_ID_LENGTH, ShowRequest


async def _show(call: ra.Call) -> object:
    return await call.route(ShowRequest(kind=call.args["kind"], id=call.args.get("id")), call.request)


SPECS = (
    ra.RouteTool(
        name="sidebar_show", route="src.api.ui_show_routes:show_item", gate=ra.ARRANGE,
        description="Show one left bar item in the window the owner used last; other windows are left alone. kind and id: session "
                    "(a sessions_list id), file (files_open's file.id), browser (a browser_open row id), board (an open board's slug), "
                    "layout (a saved layout uuid), task_manager (no id). Refused if the item is gone or no window was used yet.",
        properties={"kind": {"type": "string", "enum": list(KINDS)},
                    "id": {"type": "string", "minLength": 1, "maxLength": MAX_ID_LENGTH,
                           "description": "the item's id; leave out for task_manager"}},
        required=("kind",), invoke=_show, example={"kind": "task_manager"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)

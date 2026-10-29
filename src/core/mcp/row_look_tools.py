
from __future__ import annotations

from src.core.mcp import route_adapters as ra
from src.core.row_looks.palette import COLORS, ICONS
from src.models.row_looks import RowLookRequest


async def _set(call: ra.Call) -> object:
    args = call.args
    body = RowLookRequest(**{k: args[k] for k in ("color", "icon") if k in args})
    return await call.route(args["row"], body, call.request)


SPECS = (
    ra.RouteTool(
        name="sidebar_row_look_set", route="src.api.row_looks_routes:set_row_look", gate=ra.ARRANGE,
        description="Change the color or icon of a row already open in the owner's left sidebar (a file, a browser page or a review board). "
                    "row is the id files_open, browser_open or task_manager_board_focus answered (file.id, page.id, browser.id). Send color, icon or "
                    "both; null clears one, clearing both restores the default look. Every open window repaints.",
        properties={"row": {"type": "string", "pattern": "^[0-9a-f]{16}$", "description": "row id from files_open or browser_open"},
                    "color": {"type": ["string", "null"], "enum": [*COLORS, None], "description": "theme color name; null clears"},
                    "icon": {"type": ["string", "null"], "enum": [*ICONS, None], "description": "icon name; null clears"}},
        required=("row",), invoke=_set, example={"row": "0123456789abcdef", "color": "cyan"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)


from __future__ import annotations

from fastapi.encoders import jsonable_encoder

from src.core.mcp import route_adapters as ra
from src.core.mcp import session_target
from src.core.mcp.front_flag import FRONT_PROPERTY, bring_front
from src.core.row_looks.palette import COLORS, ICONS
from src.models.open_files import MAX_PATH_LENGTH, OpenFileRequest


async def _open(call: ra.Call) -> object:
    args = call.args
    body = OpenFileRequest(root=args.get("root", "workdir"), path=args["path"], session_uuid=call.session_uuid or "",
                           kind=args.get("kind", "file"), color=args.get("color"), icon=args.get("icon"))
    answer = await call.route(body)
    if args.get("front") is not True:
        return answer
    return {**jsonable_encoder(answer), "front": await bring_front(call.request, "file", answer.file.id)}


SPECS = (
    ra.RouteTool(
        name="files_open", route="src.api.open_files_routes:open_file", gate=ra.ARRANGE,
        description="Open a file in the owner's files list (left sidebar); the same file again reuses its row. front true also "
                    "shows it in the window the owner used last. target is the session the file belongs to; path is relative to root: "
                    "workdir (default) or user (~/.claude); kind file (default) or diff (read-only, workdir only). Optional "
                    "color and icon style the row; restyle with sidebar_row_look_set.",
        properties={"path": {"type": "string", "minLength": 1, "maxLength": MAX_PATH_LENGTH,
                             "description": "relative to root, e.g. docs/plan.md"},
                    "root": {"type": "string", "enum": ["workdir", "user"], "default": "workdir"},
                    "kind": {"type": "string", "enum": ["file", "diff"], "default": "file"},
                    "color": {"type": "string", "enum": list(COLORS), "description": "OPTIONAL row color, a theme color name"},
                    "icon": {"type": "string", "enum": list(ICONS), "description": "OPTIONAL row icon name"},
                    "front": FRONT_PROPERTY},
        required=("path",), reach=session_target.STORED, needs_uuid=True, invoke=_open,
        example={"path": "README.md"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)

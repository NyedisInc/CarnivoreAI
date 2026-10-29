
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from src.core.browsers.store import MAX_LABEL_LENGTH
from src.core.browsers.url_policy import MAX_URL_LENGTH
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.front_flag import FRONT_PROPERTY, bring_front
from src.core.row_looks.palette import COLORS, ICONS
from src.models.browsers import OpenPageRequest

_ALLOWED = {"url", "huddle_artifact", "title", "color", "icon", "front"}


def _body(args: dict) -> OpenPageRequest:
    extra = set(args) - _ALLOWED
    if extra:
        raise ToolError(f"browser_open does not take {', '.join(sorted(extra))}")
    try:
        return OpenPageRequest(**args)
    except ValidationError as exc:
        raise ToolError(f"refused: {exc.errors()[0].get('msg', 'bad arguments')}") from exc


async def browser_open(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import browser_open_routes
    from src.core.mcp.write_tools import _request, _via_route

    front = args.get("front") is True
    body = _body({k: v for k, v in args.items() if k != "front"})
    request = _request(manager)
    answer = await _via_route(browser_open_routes.open_page(body, request))
    if front:
        row = answer.get("page") or answer.get("browser") or {}
        answer = {**answer, "front": await bring_front(request, "browser", row.get("id", ""))}
    return _ok(answer)


READ_TOOLS: dict = {}
WRITE_TOOLS: dict = {
    "browser_open": (
        "Open a page for the owner; every Carnivore window shows it as a sidebar row, full size in his center screen. "
        "huddle_artifact {item, artifact} opens a page you posted (artifact is message.artifact.id); "
        "url /static/popout.html?... opens a pop-out page; url http(s) opens a site. Optional title, color and icon "
        "style the row (restyle later with sidebar_row_look_set).",
        {"huddle_artifact": {"type": "object", "additionalProperties": False, "required": ["item", "artifact"],
                             "properties": {"item": {"type": "integer", "minimum": 1},
                                            "artifact": {"type": "string", "pattern": "^[0-9a-f]{8}$"}}},
         "url": {"type": "string", "minLength": 1, "maxLength": MAX_URL_LENGTH},
         "title": {"type": "string", "maxLength": MAX_LABEL_LENGTH,
                   "description": "OPTIONAL. The sidebar row's label; default the page's own title or the host."},
         "color": {"type": "string", "enum": list(COLORS), "description": "OPTIONAL row color, a theme color name"},
         "icon": {"type": "string", "enum": list(ICONS), "description": "OPTIONAL row icon name"},
         "front": FRONT_PROPERTY},
        [], browser_open,
    ),
}
UNGATED_WRITES: frozenset = frozenset({"browser_open"})

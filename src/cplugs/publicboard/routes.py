
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, Pattern, Tuple

from src.cplugs.publicboard.read import FRAME_PATH, board, frame, shell_route
from src.cplugs.publicboard.respond import Handler

RouteKey = Tuple[str, str]
PatternRoute = Tuple[str, Pattern[str], Handler]

ROUTES: Mapping[RouteKey, Handler] = MappingProxyType({
    ("GET", "/"): shell_route("/"),
    ("GET", "/app.js"): shell_route("/app.js"),
    ("GET", "/app.css"): shell_route("/app.css"),
    ("GET", "/api/board"): board,
})
PATTERN_ROUTES: Tuple[PatternRoute, ...] = (("GET", FRAME_PATH, frame),)

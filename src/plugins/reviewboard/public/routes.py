
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, Pattern, Tuple

from src.plugins.reviewboard.public.read import FRAME_PATH, board, frame, shell_route
from src.plugins.reviewboard.public.respond import Handler
from src.plugins.reviewboard.public.waiting import wait_next
from src.plugins.reviewboard.public.write import comments, draft

RouteKey = Tuple[str, str]
PatternRoute = Tuple[str, Pattern[str], Handler]

ROUTES: Mapping[RouteKey, Handler] = MappingProxyType({
    ("GET", "/"): shell_route("/"),
    ("GET", "/publicboard.js"): shell_route("/publicboard.js"),
    ("GET", "/publicboard.css"): shell_route("/publicboard.css"),
    ("GET", "/api/board"): board,
    ("POST", "/api/comments"): comments,
    ("POST", "/api/draft"): draft,
    ("GET", "/api/next"): wait_next,
})
PATTERN_ROUTES: Tuple[PatternRoute, ...] = (("GET", FRAME_PATH, frame),)

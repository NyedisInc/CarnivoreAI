
from __future__ import annotations

import datetime as dt
import html
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from src.cplugs.flow.views.model import build_view

ASSETS = Path(__file__).with_name("assets")
MAX_BYTES = 2 * 1024 * 1024 - 64 * 1024
MAX_EVENTS = 4000
CSS_FILES = ("base.css", "hybrid.css", "gantt.css", "chat.css", "swim.css")
JS_FILES = ("core.js", "hybrid.js", "gantt.js", "chat.js", "swim.js", "main.js")


@lru_cache(maxsize=None)
def _asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


def js_source() -> str:
    return "\n".join(_asset(n) for n in JS_FILES)


def _embed(data: Dict[str, Any]) -> str:
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_html(run: Dict[str, Any], tz: Optional[dt.tzinfo] = None) -> str:
    view = build_view(run, tz)
    title = f"flow {run['seed']['kind']} {run['seed']['id']}"
    while True:
        page = (_asset("page.html").replace("/*CSS*/", "\n".join(_asset(n) for n in CSS_FILES)).replace("__TITLE__", html.escape(title))
                .replace("__DATA__", _embed(view)).replace("/*JS*/", js_source()))
        if len(page.encode("utf-8")) <= MAX_BYTES or not view["events"]:
            return page
        view["events"] = view["events"][len(view["events"]) // 5 + 1:]

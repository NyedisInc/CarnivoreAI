
from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence, Tuple

import structlog

logger = structlog.get_logger()

PAGE_KEYS = ("menu", "main")
PAGE_OPTIONAL_KEYS = ("popout",)
TOPIC_NAME = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
MAX_TOPICS = 8
PAGE_SURFACE = "panel"


def parse_page(raw: Any, views: Sequence[Mapping[str, Any]]) -> Tuple[Optional[Mapping[str, Any]], str]:
    if raw is None:
        return None, ""
    if not isinstance(raw, dict):
        return None, "page must be an object"
    unknown = sorted(set(raw) - set(PAGE_KEYS) - set(PAGE_OPTIONAL_KEYS))
    if unknown:
        logger.warning("cplug_page_unknown_keys", keys=[k[:40] for k in unknown])
    panels = {v["name"] for v in views if PAGE_SURFACE in v.get("surfaces", ())}
    declared = {v["name"] for v in views}
    page: dict[str, Any] = {}
    for key in PAGE_KEYS:
        name = raw.get(key)
        if not isinstance(name, str) or not name:
            return None, f"page.{key} must name a view"
        if name not in declared:
            return None, f"page.{key} names a view the plugin does not ship"
        if name not in panels:
            return None, f"page.{key} names a view without the panel surface"
        page[key] = name
    if "popout" in raw:
        pop = raw["popout"]
        if not isinstance(pop, (bool, dict)):
            return None, "page.popout must be a boolean or object"
        page["popout"] = dict(pop) if isinstance(pop, dict) else pop
    return page, ""


def parse_topics(raw: Any) -> Tuple[str, ...]:
    if not isinstance(raw, list):
        if raw is not None:
            logger.warning("cplug_topics_ignored", reason="not_a_list")
        return ()
    kept: list = []
    for name in raw:
        if not isinstance(name, str) or not TOPIC_NAME.match(name) or name in kept:
            logger.warning("cplug_topic_dropped", reason="bad_or_duplicate")
        elif len(kept) >= MAX_TOPICS:
            logger.warning("cplug_topic_dropped", reason="over_limit")
        else:
            kept.append(name)
    return tuple(kept)

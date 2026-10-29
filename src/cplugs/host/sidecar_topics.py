
from __future__ import annotations

import re
from typing import Callable, Optional

from src.core.resource_push.topics import CPLUG_TOPIC

KEY_PATTERN = re.compile(r"^[a-z0-9_-]{1,40}$")
TOPIC_MIN_INTERVAL = 1.0

FEED_FOLD_S = 2.0

Coalescer = Callable[[str, str, float, Optional[str]], None]


def wire_topic(install_key: str, name: str, key: Optional[str]) -> str:
    base = f"{CPLUG_TOPIC}:{install_key}:{name}"
    return f"{base}:{key}" if isinstance(key, str) and KEY_PATTERN.match(key) else base


def make_publisher(install_key_of: Callable[[str], str], coalesce: Coalescer, interval: float = TOPIC_MIN_INTERVAL) -> Callable[[str, Optional[str]], None]:

    def publish(full_topic: str, key: Optional[str]) -> None:
        _, plugin_id, name = full_topic.split(".", 2)
        install = install_key_of(plugin_id)
        base = wire_topic(install, name, None)
        coalesce(base, base, interval, wire_topic(install, name, key))

    return publish

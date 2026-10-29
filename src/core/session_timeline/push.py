
from __future__ import annotations

ACTIVITY_MIN_INTERVAL_SECONDS = 60.0
ACTIVITY_KEY = "stats_activity"
ATTENTION_MIN_INTERVAL_SECONDS = 5.0
ATTENTION_KEY = "attention_history"


def announce() -> None:
    from src.core import resource_push
    from src.core.resource_push import topics

    resource_push.notify(topics.SESSION_TIMELINE)


def announce_activity() -> None:
    from src.core import resource_push
    from src.core.resource_push import topics

    resource_push.notify_coalesced(topics.SESSION_TIMELINE, ACTIVITY_KEY, ACTIVITY_MIN_INTERVAL_SECONDS)


def announce_attention() -> None:
    from src.core import resource_push
    from src.core.resource_push import topics

    resource_push.notify_coalesced(topics.SESSION_TIMELINE, ATTENTION_KEY, ATTENTION_MIN_INTERVAL_SECONDS)

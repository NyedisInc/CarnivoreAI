
from __future__ import annotations

from src.core import resource_push
from src.core.resource_push import topics


def announce() -> None:
    resource_push.notify(topics.PACK_ROSTER)


from __future__ import annotations

from typing import Any, Callable


def listing_wake(app_state: Any) -> Callable[[], None]:
    def wake() -> None:
        publisher = getattr(app_state, "listing_publisher", None)
        if publisher is not None:
            publisher.wake()
    return wake


__all__ = ["listing_wake"]

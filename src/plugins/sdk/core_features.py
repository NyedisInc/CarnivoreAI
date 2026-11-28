
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Dict, Tuple

try:
    import structlog

    logger: Any = structlog.get_logger()
except ImportError:
    import logging

    class _FallbackLogger:
        def __init__(self) -> None:
            self._log = logging.getLogger(__name__)

        def warning(self, event: str, **kwargs: Any) -> None:
            self._log.warning("%s %s", event, kwargs)

    logger = _FallbackLogger()

NAME_KEY_PREFIX = "plugins.page.core."


@dataclass(frozen=True)
class CoreFeature:

    id: str
    module: str
    attr: str = ""

    @property
    def name_key(self) -> str:
        return f"{NAME_KEY_PREFIX}{self.id}"


_FEATURES: Tuple[CoreFeature, ...] = (
    CoreFeature("crosstalk", "src.core.crosstalk"),
    CoreFeature("pipeline", "src.core.pipeline.runtime"),
    CoreFeature("transcript_events", "src.plugins.sdk.transcript_events", "subscribe"),
    CoreFeature("timeline_events", "src.plugins.sdk.timeline_events", "subscribe"),
    CoreFeature("activity_read", "src.plugins.host.activity_reader", "ActivityReader"),
)

CORE_FEATURES: Dict[str, CoreFeature] = {f.id: f for f in _FEATURES}


def is_core_feature(feature_id: str) -> bool:
    return feature_id in CORE_FEATURES


def available(feature_id: str) -> bool:
    feature = CORE_FEATURES.get(feature_id)
    if feature is None:
        return False
    try:
        module = importlib.import_module(feature.module)
    except ImportError as exc:
        logger.warning("core_feature_unavailable", feature=feature_id, module=feature.module, error=str(exc))
        return False
    return not feature.attr or hasattr(module, feature.attr)

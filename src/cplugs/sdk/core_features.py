
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Dict, Tuple

import structlog

logger = structlog.get_logger()

NAME_KEY_PREFIX = "plugins.page.core."


@dataclass(frozen=True)
class CoreFeature:

    id: str
    module: str
    attr: str = ""

    @property
    def name_key(self) -> str:
        """The catalog key naming it on the plugins page. Output: str."""
        return f"{NAME_KEY_PREFIX}{self.id}"


_FEATURES: Tuple[CoreFeature, ...] = (
    CoreFeature("crosstalk", "src.core.crosstalk"),
    CoreFeature("pipeline", "src.core.pipeline.runtime"),
    CoreFeature("transcript_events", "src.cplugs.sdk.transcript_events", "subscribe"),
    CoreFeature("activity_read", "src.cplugs.host.activity_reader", "ActivityReader"),
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

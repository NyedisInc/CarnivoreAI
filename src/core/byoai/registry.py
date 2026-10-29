
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core.byoai.contracts import ByoaiError

logger = structlog.get_logger()

HIGHLIGHT_QUERY = "highlight"


@dataclass(frozen=True)
class FeatureOwner:

    id: str
    label_key: str
    section: str
    tab: Optional[str] = None
    control: Optional[str] = None
    override: Optional[Callable[[Any], Optional[bool]]] = field(default=None, compare=False, repr=False)
    page: Optional[str] = None

    def href(self) -> str:
        if self.page:
            return self.page
        path = f"#settings/{self.section}" + (f"/{self.tab}" if self.tab else "")
        return path + (f"?{HIGHLIGHT_QUERY}={self.control}" if self.control else "")

    def overridden(self, block: Any) -> Optional[bool]:
        if self.override is None:
            return None
        try:
            value = self.override(block)
        except (OSError, ValueError) as exc:
            logger.warning("byoai_feature_owner_override_unread", owner=self.id, error=type(exc).__name__)
            return None
        return value if isinstance(value, bool) else None


@dataclass(frozen=True)
class Feature:

    id: str
    capability: str
    label_key: str
    description_key: Optional[str] = None
    group: Optional[str] = None
    owner: Optional[FeatureOwner] = None


def feature_view(feature: Feature, block: Any) -> Dict[str, Any]:
    owner = feature.owner
    overridden = owner.overridden(block) if owner else None
    return {
        "id": feature.id, "capability": feature.capability, "label_key": feature.label_key,
        "description_key": feature.description_key, "group": feature.group,
        "owner": None if owner is None else {"id": owner.id, "label_key": owner.label_key, "href": owner.href(),
                                             "control": owner.control, "overridden": overridden},
        "hidden": overridden is False,
    }


class FeatureRegistry:

    def __init__(self) -> None:
        self._features: Dict[str, Feature] = {}

    def register_feature(self, feature_id: str, capability: str, label_key: str,
                         description_key: Optional[str] = None, *, group: Optional[str] = None,
                         owner: Optional[FeatureOwner] = None) -> Feature:
        if not feature_id or not capability or not label_key:
            raise ByoaiError("a feature needs an id, a capability and a label key")
        if feature_id in self._features:
            raise ByoaiError(f"feature {feature_id} is already registered")
        feature = Feature(feature_id, capability, label_key, description_key, group, owner)
        self._features[feature_id] = feature
        return feature

    def get(self, feature_id: str) -> Optional[Feature]:
        return self._features.get(feature_id)

    def list(self) -> List[Feature]:
        return sorted(self._features.values(), key=lambda f: f.id)


DEFAULT = FeatureRegistry()


def register_feature(feature_id: str, capability: str, label_key: str,
                     description_key: Optional[str] = None, *, group: Optional[str] = None,
                     owner: Optional[FeatureOwner] = None) -> Feature:
    return DEFAULT.register_feature(feature_id, capability, label_key, description_key, group=group, owner=owner)


def get_feature(feature_id: str) -> Optional[Feature]:
    return DEFAULT.get(feature_id)


def list_features() -> List[Feature]:
    return DEFAULT.list()

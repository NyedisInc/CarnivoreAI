
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, FrozenSet, Mapping, Optional

SERVED_API_VERSIONS: FrozenSet[int] = frozenset({1})
API_VERSION_KEY = "api_version"
MANIFEST_FILE = "carnivore.json"


class ApiVersionUnsupported(ValueError):

    def __init__(self, version: Any, served: FrozenSet[int] = SERVED_API_VERSIONS) -> None:
        self.version = version
        self.served = served
        listed = ", ".join(str(v) for v in sorted(served))
        super().__init__(f"api_version {version!r} is not served by this app (it serves {listed}); "
                         f"build the plugin against a served contract or update the app")


def is_served(version: Any) -> bool:
    return isinstance(version, int) and not isinstance(version, bool) and version in SERVED_API_VERSIONS


def require_served(doc: Mapping[str, Any]) -> None:
    if API_VERSION_KEY in doc and not is_served(doc[API_VERSION_KEY]):
        raise ApiVersionUnsupported(doc[API_VERSION_KEY])


def read_api_version(folder: Path) -> Optional[int]:
    try:
        doc = json.loads((Path(folder) / MANIFEST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = doc.get(API_VERSION_KEY) if isinstance(doc, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None

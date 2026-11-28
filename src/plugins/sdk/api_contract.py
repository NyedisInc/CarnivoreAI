
from __future__ import annotations

import json
import tomllib
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
    folder_path = Path(folder)
    toml_path = folder_path / "carnivore.toml"
    try:
        has_toml = toml_path.is_file()
    except OSError:
        return None
    if has_toml:
        try:
            doc = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            return None
        if not isinstance(doc, dict):
            return None
        if API_VERSION_KEY in doc:
            value = doc[API_VERSION_KEY]
            return value if isinstance(value, int) and not isinstance(value, bool) else None
        return 1 if type(doc.get("schema")) is int and doc.get("schema") == 2 else None
    try:
        doc = json.loads((folder_path / MANIFEST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = doc.get(API_VERSION_KEY) if isinstance(doc, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None

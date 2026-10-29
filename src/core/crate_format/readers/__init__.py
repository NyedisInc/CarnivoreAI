
from __future__ import annotations

from typing import Any, Callable, Dict

from src.core.crate_format.model import CrateManifest
from src.core.crate_format.promise import check_readable
from src.core.crate_format.readers import v1

UPGRADERS: Dict[int, Callable[[Any], CrateManifest]] = {1: v1.to_current}


def load(manifest_json: Any) -> CrateManifest:
    major, _ = check_readable(manifest_json)
    return UPGRADERS[major](manifest_json)

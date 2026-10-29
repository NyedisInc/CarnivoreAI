
from __future__ import annotations

from typing import Any

from src.core.crate_format.model import CrateManifest


def to_current(manifest_json: Any) -> CrateManifest:
    return CrateManifest.from_json(manifest_json)

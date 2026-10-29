
from __future__ import annotations

from typing import Any, Tuple

from src.core.crate_format.constants import FORMAT, FORMAT_MAJOR
from src.core.crate_format.errors import CrateMalformed, CrateTooNew


def check_readable(manifest_json: Any) -> Tuple[int, int]:
    if not isinstance(manifest_json, dict):
        raise CrateMalformed(["crate.json is not a JSON object"])
    if manifest_json.get("format") != FORMAT:
        raise CrateMalformed([f"crate.json format is not {FORMAT!r}"])
    version = manifest_json.get("format_version")
    if (not isinstance(version, list) or len(version) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in version)):
        raise CrateMalformed(["crate.json format_version is not [major, minor]"])
    major, minor = version
    if major < 1:
        raise CrateMalformed([f"crate.json format major {major} was never written"])
    if major > FORMAT_MAJOR:
        raise CrateTooNew(major)
    return major, minor

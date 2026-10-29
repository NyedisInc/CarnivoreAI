
from __future__ import annotations

import hashlib
import json
from typing import Any, List, Optional, Tuple, Union

from pydantic import ValidationError

from src.cplugs.reviewboard import rules
from src.cplugs.reviewboard.schema import SCHEMA_ID, SCHEMA_VERSION, Sidecar

SIDECAR_FILE = "sidecar.json"


class SidecarInvalid(ValueError):

    def __init__(self, problems: List[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _where(loc: Tuple[Union[int, str], ...]) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "(top)"


def schema_version_of(raw: Any) -> Optional[int]:
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA_ID:
        return None
    version = raw.get("schema_version")
    return version if isinstance(version, int) and not isinstance(version, bool) else None


def is_newer(raw: Any) -> bool:
    version = schema_version_of(raw)
    return version is not None and version > SCHEMA_VERSION


def parse_sidecar(raw: Any) -> Sidecar:
    try:
        sidecar = Sidecar.model_validate(raw)
    except ValidationError as exc:
        raise SidecarInvalid([f"{_where(e['loc'])}: {e['msg']}" for e in exc.errors()]) from exc
    problems = rules.check(sidecar)
    if problems:
        raise SidecarInvalid(problems)
    return sidecar


def canonical_text(sidecar: Sidecar) -> str:
    return json.dumps(sidecar.model_dump(mode="json", by_alias=True), indent=2, ensure_ascii=False) + "\n"


def etag(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

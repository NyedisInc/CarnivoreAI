from __future__ import annotations

import os
from typing import List, Mapping, Optional


def bytecode_flags(env: Optional[Mapping[str, str]] = None) -> List[str]:
    source = os.environ if env is None else env
    prefix = source.get("PYTHONPYCACHEPREFIX")
    if prefix:
        return ["-X", f"pycache_prefix={prefix}"]
    if source.get("PYTHONDONTWRITEBYTECODE"):
        return ["-B"]
    return []

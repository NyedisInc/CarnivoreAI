
from __future__ import annotations

import os
import uuid
from pathlib import Path


def unique_tmp_path(path: Path) -> Path:
    return path.with_suffix(
        f"{path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )

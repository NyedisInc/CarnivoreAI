
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List


def whole_lines(files: List[Dict[str, Any]], dest: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for entry in files:
        target = os.path.join(dest, entry["rel"])
        os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
        with open(entry["path"], "rb") as src:
            data = src.read()
        if entry["rel"].endswith(".jsonl"):
            data = data[:data.rfind(b"\n") + 1]
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as dst:
            dst.write(data)
        out.append({**entry, "path": target, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return out

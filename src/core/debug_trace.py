
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.product_identity import env_value

_SECRET_HINTS = ("token", "secret", "key", "password", "authorization", "cookie")

_MAX_VALUE_CHARS = 600

_MAX_BYTES = 8 * 1024 * 1024

_lock = threading.Lock()


def enabled() -> bool:
    raw = env_value("DEBUG")
    if raw is None:
        try:
            from src.config import settings

            raw = getattr(settings, "cloude_debug", None)
        except Exception:
            raw = None
    return str(raw or "").strip().lower() in ("1", "true", "yes", "on")


def fingerprint(value: Any) -> str:
    text = "" if value is None else str(value)
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"len={len(text)} fp={digest}"


def is_secret_name(key: str) -> bool:
    parts = re.split(r"[^a-z0-9]+", str(key).lower())
    return any(part in _SECRET_HINTS for part in parts if part)


def scrub(payload: Any) -> Any:
    if isinstance(payload, dict):
        out: Dict[str, Any] = {}
        for key, value in payload.items():
            secret = is_secret_name(key) and isinstance(value, str)
            out[str(key)] = fingerprint(value) if secret else scrub(value)
        return out
    if isinstance(payload, (list, tuple)):
        return [scrub(v) for v in payload]
    if isinstance(payload, str) and len(payload) > _MAX_VALUE_CHARS:
        return payload[:_MAX_VALUE_CHARS] + f"...<truncated {len(payload)} chars>"
    return payload


def _trace_path() -> Optional[Path]:
    try:
        from src.config import settings

        base = Path(settings.get_state_dir()) / "debug"
    except Exception:
        override = env_value("DEBUG_DIR")
        if not override:
            return None
        base = Path(override)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return base / "trace.jsonl"


def trace(event: str, **fields: Any) -> None:
    if not enabled():
        return
    try:
        path = _trace_path()
        if path is None:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "pid": os.getpid(),
        }
        record.update(scrub(fields))
        line = json.dumps(record, default=str, sort_keys=True) + "\n"
        with _lock:
            try:
                if path.exists() and path.stat().st_size + len(line) > _MAX_BYTES:
                    path.replace(path.with_suffix(".jsonl.1"))
            except OSError:
                pass
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
    except Exception:
        return

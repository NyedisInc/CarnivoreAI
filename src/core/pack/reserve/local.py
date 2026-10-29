
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from src.core.pack.machines import runtime
from src.core.pack.reserve import model


def active_reserve(wired: Any = None) -> Optional[Dict[str, Any]]:
    wired = wired or runtime.wiring()
    if wired is None:
        return None
    cfg = wired.state.reserve()
    return model.active(cfg, datetime.now(), wired.runtime.collector.hid_idle_seconds(cfg.keyboard_rule.enabled))

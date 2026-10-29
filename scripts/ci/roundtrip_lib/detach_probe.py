#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

SURVIVOR_ID = "roundtrip-b"
SURVIVOR_TMUX = "cloude_roundtrip-b"


def run_detach_sequence(install: Path) -> dict:
    sys.path.insert(0, str(install))
    from src.config import Settings  # noqa: PLC0415
    from src.core.session_manager import SessionManager  # noqa: PLC0415
    from src.models import Session  # noqa: PLC0415

    mgr = SessionManager()
    mgr._load_session_metadata()
    before = mgr._registry.current_session()
    mgr._clear_stale_metadata()
    survivor = Session(id=SURVIVOR_ID, working_dir="/tmp", tmux_session=SURVIVOR_TMUX)
    mgr._registry.register(survivor, None)
    mgr._owned.names = {SURVIVOR_TMUX}
    mgr._save_session_metadata()
    path = Path(Settings().get_session_metadata_path())
    persisted = json.loads(path.read_text()).get("id") if path.exists() else None
    return {
        "rehydrated_before_detach": None if before is None else before.id,
        "persisted_after_detach": persisted,
        "resolved": str(path),
    }


def main() -> int:
    try:
        result = run_detach_sequence(Path.cwd())
    except (ImportError, AttributeError, TypeError, OSError, ValueError) as exc:
        result = {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=4)}
        print(json.dumps(result))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from contextlib import closing


def measure() -> dict:
    sys.path.insert(0, ".")
    from src.api import projects_service
    from src.config import Settings
    from src.core.db import connect, db_path_for

    settings = Settings()
    with open(settings.auth_config_file) as fh:
        config_names = [p["name"] for p in json.load(fh).get("projects", [])]
    with closing(connect(db_path_for(settings.get_state_dir()))) as conn:
        db_names = [r[0] for r in conn.execute("SELECT display_name FROM projects")]
    view = projects_service.current_view(settings)
    missing = [n for n in config_names if n not in db_names]
    return {
        "config_projects": config_names,
        "db_projects": db_names,
        "served_mode": view.mode,
        "served_degraded": view.degraded,
        "in_config_but_not_in_db": missing,
        "silent_loss": bool(missing) and not view.degraded,
    }


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2, ensure_ascii=False))

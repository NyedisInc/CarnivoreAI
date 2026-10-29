#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

FUTURE_VERSION = 99


def measure() -> dict:
    sys.path.insert(0, ".")
    from src.core.config_migration import CURRENT_CONFIG_VERSION, migrate_config_dict

    future = {"config_version": FUTURE_VERSION, "projects": [], "agents": {}}
    out, changed = migrate_config_dict(dict(future), False, False)
    return {
        "current_config_version": CURRENT_CONFIG_VERSION,
        "input_version": FUTURE_VERSION,
        "changed": changed,
        "raised_or_refused": False,
        "output_version": out.get("config_version"),
        "verdict": ("a config from the future is silently accepted as current"
                    if not changed else "the migration altered a future config"),
    }


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2))

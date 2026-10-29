
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def require_config_file(config_path: Path) -> None:
    if not config_path.exists():
        raise FileNotFoundError(
            f"Auth config file not found: {config_path}\n"
            f"Run ./setup_auth.py to create it."
        )


def read_config(config_path: Path) -> Dict[str, Any]:
    require_config_file(config_path)
    try:
        with open(config_path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Invalid JSON in auth config file: {e}\n"
            f"Check {config_path}"
        )


def read_config_text(config_path: Path) -> tuple[str, Dict[str, Any]]:
    require_config_file(config_path)
    with open(config_path) as f:
        raw = f.read()
    try:
        return raw, json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Invalid JSON in auth config file: {e}\n"
            f"Check {config_path}"
        )

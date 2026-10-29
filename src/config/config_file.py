
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def require_config_file(config_path: Path) -> None:
    """Refuse early, and by name, when ``config.json`` is not there.

    Description: one copy of a message four call sites used to spell out
      identically. It names the path AND the command that creates it,
      because the reader of this error is usually someone who has never
      run setup.
    Inputs: config_path (Path).
    Output: None.
    Raises:
        FileNotFoundError: the file does not exist.
    Example: require_config_file(Path("~/config.json").expanduser())
    """
    if not config_path.exists():
        raise FileNotFoundError(
            f"Auth config file not found: {config_path}\n"
            f"Run ./setup_auth.py to create it."
        )


def read_config(config_path: Path) -> Dict[str, Any]:
    """Read and parse ``config.json``.

    Description: a decode failure becomes a ``ValueError`` naming the
      file, because every caller of this is answering an API request and
      a raw ``JSONDecodeError`` says nothing about WHICH file is broken.
    Inputs: config_path (Path).
    Output: dict - the parsed document.
    Raises:
        FileNotFoundError: the file does not exist.
        ValueError: the file is not valid JSON.
    Example: read_config(path)["agents"]
    """
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

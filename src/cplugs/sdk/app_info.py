
from __future__ import annotations

from pathlib import Path
from typing import Optional


def app_version() -> str:
    from src.core.version import resolve_version  # noqa: PLC0415

    return resolve_version() or ""


def repo_root() -> Optional[Path]:
    from src.core.product_identity import env_value  # noqa: PLC0415
    from src.core.version import repo_root as source_root  # noqa: PLC0415

    named = env_value("REPO_ROOT")
    candidate = Path(named).expanduser() if named else source_root()
    return candidate if (candidate / ".git").exists() else None


def git_available() -> bool:
    from src.core.dev_tools import git_guard  # noqa: PLC0415

    return git_guard.git_available()


def developer_mode_on() -> bool:
    from src.cplugs.host import developer_mode  # noqa: PLC0415

    return developer_mode.is_on()


def renamed_widget_key(key: str) -> str:
    from src.core.widget_placement.retired_widgets import RENAMED_WIDGETS  # noqa: PLC0415

    head, sep, tail = key.partition(":")
    return f"{RENAMED_WIDGETS.get(head, head)}{sep}{tail}"

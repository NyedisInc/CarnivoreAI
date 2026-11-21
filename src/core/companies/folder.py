
from __future__ import annotations

import os
from typing import Any

from src.core.project_directory import allowed_roots, canonical_path, within_roots


class CompanyFolderInvalid(ValueError):
    pass


def canonical_company_folder(raw: Any, settings: Any = None) -> str:
    text = raw.strip() if isinstance(raw, str) else ""
    if not text or "\x00" in text:
        raise CompanyFolderInvalid("a company folder is a path to an existing folder")
    try:
        path = canonical_path(text)
    except (OSError, ValueError) as exc:
        raise CompanyFolderInvalid(f"that path cannot be resolved: {exc}") from exc
    if not os.path.isdir(path):
        raise CompanyFolderInvalid(f"{path} is not an existing folder")
    if not within_roots(path, allowed_roots(settings)) or path in allowed_roots(settings):
        raise CompanyFolderInvalid(f"{path} is outside your own folders, or is the top of them")
    return path

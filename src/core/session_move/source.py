
from __future__ import annotations

import os
from typing import Optional

SOURCE_TEMP = "temp"

SOURCE_HOME = "home"

TEMP_FOLDER_PREFIX = "ses_"


def _real(path: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def classify_source(working_dir: Optional[str], *, temp_root: str, home: str) -> Optional[str]:
    if not working_dir or not str(working_dir).strip():
        return None
    real = _real(str(working_dir))
    if real == _real(home):
        return SOURCE_HOME
    if os.path.dirname(real) == _real(temp_root) and os.path.basename(real).startswith(TEMP_FOLDER_PREFIX):
        return SOURCE_TEMP
    return None

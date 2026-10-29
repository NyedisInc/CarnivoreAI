
from __future__ import annotations

import os

from src.core.deepsearch import fallback_hook
from src.core.pipeline import runtime


def install() -> bool:
    if os.environ.get("CLOUDE_TEST_MODE") == "1" or os.environ.get("CLOUDE_SAVE_PIPELINE") == "0":
        return False
    fallback_hook.begin_boot()
    runtime.start()
    return True


def uninstall() -> None:
    runtime.stop()
    fallback_hook.end_boot()

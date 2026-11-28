
from __future__ import annotations

import os

from src.core.deepsearch import fallback_hook
from src.core.pipeline import runtime
from src.core.product_identity import test_mode_enabled


BOOT_SCAN_DELAY_SECONDS: float = 15.0


def install() -> bool:
    if test_mode_enabled() or os.environ.get("CLOUDE_SAVE_PIPELINE") == "0":
        return False
    fallback_hook.begin_boot()
    runtime.start(boot_scan_delay=BOOT_SCAN_DELAY_SECONDS)
    return True


def uninstall() -> None:
    runtime.stop()
    fallback_hook.end_boot()


from __future__ import annotations

import platform


def this_label() -> str:
    return platform.node().split(".")[0][:64] or "this computer"

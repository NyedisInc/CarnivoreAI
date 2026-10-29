
from __future__ import annotations

from typing import Any, Dict, List


def plugin_widget_rows() -> List[Dict[str, Any]]:
    from src.cplugs.registry import CPLUGS  # noqa: PLC0415

    return [
        {"id": f"{cplug.manifest.id}.{name}", **block}
        for cplug in CPLUGS
        for name, block in cplug.manifest.widgets.items()
    ]

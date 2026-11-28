
from __future__ import annotations

from typing import Any, Dict, List

from src.plugins.sdk.renamed_from import KEEP_WIDGETS, kept_old_id, widget_id


def plugin_widget_rows() -> List[Dict[str, Any]]:
    from src.plugins.registry import CPLUGS  # noqa: PLC0415

    return [
        {"id": widget_id(cplug.manifest.id, kept_old_id(cplug.manifest.renamed_from, cplug.manifest.renamed_from_keeps, KEEP_WIDGETS), name), **block}
        for cplug in CPLUGS
        for name, block in cplug.manifest.widgets.items()
    ]

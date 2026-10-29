
from __future__ import annotations

from typing import Iterable, List, Sequence

from src.core.skills.kinds import KIND_THEME
from src.core.skills.ledger_types import SCOPE_GLOBAL, InstalledItem
from src.models.themes import ThemeManifest

BUNDLED_HANDLE = "bundled"


def stamp(
    manifests: Sequence[ThemeManifest],
    theme_installs: Iterable[InstalledItem],
) -> List[ThemeManifest]:
    by_folder_name = {
        item.name: item
        for item in theme_installs
        if item.kind == KIND_THEME and item.scope == SCOPE_GLOBAL
    }
    stamped: List[ThemeManifest] = []
    for manifest in manifests:
        if manifest.source == "builtin":
            stamped.append(
                manifest.model_copy(
                    update={
                        "feedbackItemId": f"{BUNDLED_HANDLE}/{manifest.id}",
                        "publisher": None,
                    }
                )
            )
            continue
        installed = by_folder_name.get(manifest.id)
        if installed is None:
            stamped.append(
                manifest.model_copy(
                    update={"feedbackItemId": None, "publisher": None}
                )
            )
            continue
        stamped.append(
            manifest.model_copy(
                update={
                    "feedbackItemId": installed.item_id,
                    "publisher": installed.publisher,
                }
            )
        )
    return stamped

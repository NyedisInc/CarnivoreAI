
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Mapping

from src.cplugs.sdk import crate_sources as cs


@dataclass(frozen=True)
class CrateEnv:

    state: Path
    locations: cs.Locations
    work: Path
    settings: Mapping[str, Any] = field(default_factory=dict)
    live_panes: Callable[[], cs.PaneListing] = cs.live_panes

    def setting(self, key: str, default: Any = "") -> Any:
        return self.settings.get(key, default)

    def with_settings(self, **values: Any) -> "CrateEnv":
        merged: Dict[str, Any] = dict(self.settings)
        merged.update(values)
        return replace(self, settings=merged)


def from_ctx(ctx: Any) -> CrateEnv:
    from src.cplugs.sdk.transcript_files import state_dir

    return CrateEnv(state=Path(state_dir()), locations=cs.locations(), work=Path(ctx.storage.path),
                    settings=ctx.settings_now())

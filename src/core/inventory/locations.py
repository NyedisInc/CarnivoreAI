
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple

CODEX_HOME_ENV = "CODEX_HOME"
PINNED_THEMES_FILE = "pinned_themes.json"
UNREAD_STATE_FILE = "unread_state.json"


def claude_homes() -> List[Path]:
    from src.core.claude_config.transcript_roots import claude_transcript_roots

    out: List[Path] = []
    for root in claude_transcript_roots():
        home = Path(root).parent
        if home not in out:
            out.append(home)
    return out


def codex_home() -> Path:
    return Path(os.environ.get(CODEX_HOME_ENV) or (Path.home() / ".codex")).expanduser()


@dataclass(frozen=True)
class Locations:

    state_dir: Path
    config_path: Path
    pins_path: Optional[Path] = None
    unread_path: Optional[Path] = None
    homes: Optional[Tuple[Path, ...]] = None
    codex: Optional[Path] = None
    plugin_manifests: Optional[Tuple[Any, ...]] = None
    plugin_settings: Optional[Mapping[str, Mapping[str, Any]]] = None
    plugin_enabled: Optional[Mapping[str, bool]] = None

    def claude_homes(self) -> List[Path]:
        return [Path(h) for h in self.homes] if self.homes is not None else claude_homes()

    def codex_home(self) -> Path:
        return Path(self.codex) if self.codex is not None else codex_home()

    def pinned_themes(self) -> Path:
        return Path(self.pins_path) if self.pins_path is not None else Path(self.state_dir) / PINNED_THEMES_FILE

    def unread_state(self) -> Path:
        return Path(self.unread_path) if self.unread_path is not None else Path(self.state_dir) / UNREAD_STATE_FILE

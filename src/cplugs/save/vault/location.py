
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.cplugs.save.vault import constants as K
from src.cplugs.sdk import destination_rules, transcript_files as tf, vault_health


class VaultUnavailable(RuntimeError):
    pass


def location_of(config: Dict[str, Any]) -> str:
    return vault_health.location_of(config)


def read_location(config_path: Optional[Path] = None, state_dir: Optional[Path] = None) -> str:
    return vault_health.configured_location(Path(state_dir or tf.state_dir()), config_path or tf.config_file())


def resolve_root(state_dir: Path, config_path: Optional[Path] = None) -> Path:
    return vault_health.resolve_root(Path(state_dir), config_path or tf.config_file())


def refusals(value: str) -> List[str]:
    return destination_rules.refusals(value)


def open_root(state_dir: Path, config_path: Optional[Path] = None) -> Path:
    chosen = read_location(config_path, state_dir)
    problems = refusals(chosen) if chosen else []
    if problems:
        raise VaultUnavailable(problems[0])
    return ensure_root(resolve_root(state_dir, config_path))


def transcripts_disk_warning(root: Path, transcripts: Optional[Path]) -> Optional[str]:
    return destination_rules.same_disk_warning(str(root), transcripts) if transcripts is not None else None


def _volume_of(root: Path, removable_parent: str) -> Optional[Path]:
    parent = Path(removable_parent)
    try:
        rel = root.relative_to(parent)
    except ValueError:
        return None
    return parent / rel.parts[0] if rel.parts else None


def ensure_root(root: Path, *, removable_parent: str = K.REMOVABLE_PARENT,
                ismount: Callable[[str], bool] = os.path.ismount) -> Path:
    volume = _volume_of(root, removable_parent)
    if volume is not None and not ismount(str(volume)):
        raise VaultUnavailable(f"the vault location {root} is on {volume}, which is not mounted")
    if not root.is_dir():
        if not root.parent.is_dir():
            raise VaultUnavailable(f"the vault location {root} has no parent folder; nothing was created")
        try:
            root.mkdir()
        except OSError as exc:
            raise VaultUnavailable(f"cannot create the vault folder {root}: {exc}") from exc
    marker = root / K.MARKER_NAME
    if marker.exists():
        return root
    foreign = [p.name for p in root.iterdir() if not p.name.startswith(".")]
    if foreign:
        raise VaultUnavailable(f"{root} holds files but is not a vault; choose an empty folder")
    try:
        marker.write_text(json.dumps({"format": K.FORMAT_VERSION, "kind": "carnivore-vault"}), encoding="utf-8")
    except OSError as exc:
        raise VaultUnavailable(f"cannot write to the vault folder {root}: {exc}") from exc
    return root

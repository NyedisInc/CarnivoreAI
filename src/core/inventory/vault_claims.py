
from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

from src.core.backup_health import vault_record
from src.core.inventory.file_trace import measured_artifact
from src.core.inventory.locations import Locations
from src.core.inventory.model import REPORT, ROLE_KEY, ROLE_PATH, Artifact, FieldRef


STORE_VAULT = "backup-vault"
_VAULT_REWRITE = (FieldRef("folder name: <conversation id>", ROLE_KEY), FieldRef("<point>.json#files[].source_path", ROLE_PATH),
                  FieldRef("<point>.json#working_dir", ROLE_PATH), FieldRef("<point>.json#project_uid", ROLE_KEY))


def vault_root(locations: Locations) -> Path:
    return vault_record.resolve_root(Path(locations.state_dir), Path(locations.config_path))


def vault_manifests(locations: Locations, conversations: Sequence[str], blockers: List[str]) -> List[Artifact]:
    folder = vault_root(locations) / vault_record.MANIFESTS_DIR
    out: List[Artifact] = []
    for conv in conversations:
        path = folder / conv
        if not path.is_dir():
            continue
        art = measured_artifact(STORE_VAULT, str(path), folder, REPORT,
                                "the conversation's points in the backup vault; its chunks are shared by content with other "
                                "conversations and are removed only by the vault's own collector", blockers, _VAULT_REWRITE)
        if art is not None:
            out.append(art)
    return out

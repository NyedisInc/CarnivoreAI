
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List

import structlog

from src.cplugs.save.service import RUNTIME
from src.cplugs.save.vault import points as vault_points
from src.cplugs.save.vault import restore
from src.cplugs.save.vault.location import VaultUnavailable
from src.cplugs.save.vault.manifest import ManifestError
from src.cplugs.save.vault.store import Vault
from src.cplugs.sdk import restore_points

logger = structlog.get_logger()


class RestorePoints:

    def __init__(self, vault: Callable[[], Vault] = RUNTIME.vault) -> None:
        self._vault = vault

    def list_points(self, conversation_id: str) -> List[Dict[str, Any]]:
        try:
            return vault_points.list_points(self._vault(), conversation_id)
        except VaultUnavailable as exc:
            raise OSError(str(exc)) from exc
        except ManifestError as exc:
            raise ValueError(str(exc)) from exc

    def restore_newest(self, conversation_id: str, corpus_root: Path) -> Path:
        try:
            vault = self._vault()
            points = vault_points.list_points(vault, conversation_id)
            if not points:
                raise restore_points.NoRestorePoint(conversation_id)
            done = vault_points.restore_point(vault, conversation_id, points[0]["id"], {"claude": Path(corpus_root).parent, "claude/projects": Path(corpus_root)})
        except (VaultUnavailable, ManifestError, restore.RestoreError, OSError) as exc:
            raise restore_points.RestoreFailed(str(exc)) from exc
        logger.info("save_restore_newest", conversation_id=conversation_id, point_id=points[0]["id"])
        return done.transcript_path

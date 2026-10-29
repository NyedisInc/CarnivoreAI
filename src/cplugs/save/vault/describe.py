
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import digest as digest_mod
from src.cplugs.save.vault.manifest import Manifest


def describe(manifest: Manifest, pinned: bool, tags: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    main = manifest.main()
    digest = digest_mod.merge(main.digests) if main is not None and main.digests else None
    return {
        "id": manifest.point_id, "kind": "point", "conversation_id": manifest.conversation_id or manifest.unit,
        "session_uuid": manifest.session_uuid, "project": manifest.project_name, "project_uid": manifest.project_uid,
        "working_dir": manifest.working_dir, "encoded_folder": manifest.encoded_folder, "agent_family": manifest.family,
        "wrapper": manifest.wrapper, "reason": manifest.reason, "created_at": manifest.created_at,
        "created_epoch": manifest.created_epoch, "turns": digest["turns"] if digest else None, "codec": "vault", "raw_bytes": manifest.raw_bytes(),
        "packed_bytes": sum(f.stored_bytes for f in manifest.files), "disk_bytes": sum(f.stored_bytes for f in manifest.files),
        "has_subagents": any(f.role == K.ROLE_SUBAGENT for f in manifest.files), "files": len(manifest.files),
        "pinned": pinned, "digest": digest, "has_summary": False, "summary_method": None,
        "legacy": manifest.legacy_key is not None,
        "imported": bool(tags and tags.get("imported")), "labels": list((tags or {}).get("labels") or []), "group": (tags or {}).get("group"),
        "original_folder": (tags or {}).get("original_folder"),
    }

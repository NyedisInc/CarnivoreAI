
from __future__ import annotations

import time
from typing import Dict, List, Optional

import structlog

from src.plugins.save.vault.chunks import BlobStore
from src.plugins.save.vault.manifest import Manifest
from src.plugins.sdk.blob_codec import BlobCorrupt, BlobMissing, ChunkRef, Throttle

logger = structlog.get_logger()


class CheckIncomplete(RuntimeError):
    pass


class CheckCancelled(CheckIncomplete):
    pass


class StoreUnreachable(CheckIncomplete):
    pass


def bad_chunks(blobs: BlobStore, manifest: Manifest, pace: Optional[Throttle] = None) -> List[str]:
    folder = blobs.folder_identity()
    if folder is None:
        raise StoreUnreachable("the vault's chunk folder is not there")
    bad: Dict[str, str] = {}
    seen = set()
    for entry in manifest.files:
        started = time.monotonic()
        for ref in entry.chunks:
            if pace is not None and pace.cancelled:
                raise CheckCancelled("the check was cancelled")
            if ref.sha256 in seen:
                continue
            seen.add(ref.sha256)
            reason = _read_one(blobs, ref)
            if reason:
                if blobs.folder_identity() != folder:
                    raise StoreUnreachable("the vault's chunk folder went away during the check")
                bad[ref.sha256] = reason
        if pace is not None:
            pace.rest(time.monotonic() - started)
    if bad:
        logger.warning("offload_chunks_bad", unit=manifest.unit, count=len(bad), reasons=sorted(set(bad.values())))
    return sorted(bad)


def _read_one(blobs: BlobStore, ref: ChunkRef) -> str:
    try:
        blobs.get(ref)
    except BlobMissing:
        return "missing"
    except BlobCorrupt:
        return "damaged"
    except (OSError, ValueError) as exc:
        logger.error("offload_chunk_unreadable", chunk=ref.sha256[:12], error_type=type(exc).__name__, error=str(exc)[:200])
        return "unreadable"
    return ""

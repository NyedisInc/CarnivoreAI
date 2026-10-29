
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List

import structlog

from src.cplugs.save.vault.manifest import ManifestError
from src.cplugs.save.vault.old_sources import runs
from src.cplugs.save.vault.store import Vault
from src.cplugs.sdk.blob_codec import BlobCorrupt, BlobMissing

logger = structlog.get_logger()
LISTED_FAILURES = 50
_FILED = ("adopted", "present")


def _file_failure(vault: Vault, unit: str, point_id: str, want: Dict[str, Any]) -> str:
    try:
        manifest = vault.manifests.read(unit, point_id)
    except ManifestError as exc:
        return f"manifest unreadable: {str(exc)[:80]}"
    entry = next((e for e in manifest.files if (e.home, e.rel) == (want["home"], want["rel"])), None)
    if entry is None:
        return "file missing from the point"
    digest, length = hashlib.sha256(), 0
    try:
        for ref in entry.chunks:
            raw = vault.blobs.get(ref)
            digest.update(raw)
            length += len(raw)
    except (BlobMissing, BlobCorrupt, OSError) as exc:
        return f"chunk unreadable: {type(exc).__name__}"
    if length != want["length"] or digest.hexdigest() != want["sha256"]:
        return "bytes differ from what the run filed"
    return ""


def verify_run(vault: Vault, state: Path, run_id: str) -> Dict[str, Any]:
    receipt = runs.read_receipt(state, run_id)
    filed = {(p["unit"], p.get("source_point_id")): p for p in receipt.get("points") or [] if p.get("status") in _FILED}
    failures: List[Dict[str, str]] = []
    files = byte_total = checked = 0
    for row in runs.read_expected(state, run_id):
        placed = filed.get((row["unit"], row["source_point_id"]))
        if placed is None:
            continue  # nothing was written
        checked += 1
        why_not = ""
        try:
            tags = vault.manifests.read_tags(row["unit"], placed["point_id"])
        except ManifestError as exc:
            tags, why_not = {}, f"tags unreadable: {str(exc)[:60]}"
        if not why_not and not vault.manifests.is_kept(row["unit"], placed["point_id"]):
            why_not = "keep marker missing"
        if not why_not and not tags.get("imported"):
            why_not = "tags missing"
        if why_not:
            failures.append({"unit": row["unit"], "point": placed["point_id"], "file": "", "reason": why_not})
        for want in row["files"]:
            files += 1
            byte_total += int(want["length"])
            reason = _file_failure(vault, row["unit"], placed["point_id"], want)
            if reason:
                failures.append({"unit": row["unit"], "point": placed["point_id"], "file": want["rel"], "reason": reason})
    copies = dict((receipt.get("counts") or {}).get("copies") or {})
    total = int(copies.pop("total", 0))
    return {"run_id": run_id, "ok": not failures and receipt.get("state") in (runs.STATE_DONE, runs.STATE_NOOP),
            "state": receipt.get("state"), "points": {"checked": checked, "failed": len({(f["unit"], f["point"]) for f in failures})},
            "files": files, "bytes": byte_total, "failures": {"total": len(failures), "first": failures[:LISTED_FAILURES]},
            "reconciliation": {"copies": total, "buckets": copies, "unaccounted": total - sum(copies.values()),
                               "refused_at_filing": len(receipt.get("refused") or [])}}

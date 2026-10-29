
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.catalog import grade_lint, publish_digest, publish_prepare

MAX_MANIFEST_BYTES = 64 * 1024
MAX_FILES_LISTED = 500
_MANIFESTS = {"theme": "theme.json", "plugin": ".claude-plugin/plugin.json", "mod": ".claude-plugin/plugin.json", "cplug": "cplug.json"}
_LICENSE_FILE = re.compile(r"^(licen[sc]e|copying|unlicense)(\.(md|txt))?$", re.IGNORECASE)
_SPDX_OPERATORS = {"AND", "OR", "WITH"}
_POLICY = Path(__file__).resolve().parents[2] / "schemas" / "extensions" / "warez" / "policy.json"


def _manifest(kind: str, folder_path: str) -> Dict[str, Any]:
    folder = Path(folder_path)
    if kind == "skill":
        return grade_lint.read_manifest(folder)
    rel = _MANIFESTS.get(kind)
    target = folder / rel if rel else None
    try:
        if target is None or target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_MANIFEST_BYTES:
            return {}
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _text(value: Any) -> str:
    return str(value).strip()[:64] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def declared_version(kind: str, folder_path: str) -> str:
    manifest = _manifest(kind, folder_path)
    found = _text(manifest.get("version"))
    if not found and kind == "skill":
        meta = manifest.get("metadata")
        found = _text(meta.get("version")) if isinstance(meta, dict) else ""
    return found


def _allowed_licenses() -> frozenset:
    try:
        return frozenset(json.loads(_POLICY.read_text(encoding="utf-8")).get("licenses", []))
    except (OSError, ValueError):
        return frozenset()


def declared_license(kind: str, folder_path: str) -> str:
    expression = _text(_manifest(kind, folder_path).get("license"))
    tokens = [t for t in expression.replace("(", " ").replace(")", " ").split() if t not in _SPDX_OPERATORS]
    allowed = _allowed_licenses()
    return expression if tokens and all(t in allowed for t in tokens) else ""


def _mtime(folder: Path, rel: str) -> Optional[float]:
    try:
        target = folder / rel
        return None if target.is_symlink() else os.stat(target).st_mtime
    except OSError:
        return None


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def build(loc: Dict[str, Any], prepared: publish_prepare.Prepared, sends: List[Dict[str, Any]],
          checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    kind, folder = prepared.kind, Path(loc["path"])
    now_map = publish_digest.file_map(prepared.members)
    changed: List[str] = publish_digest.changed_paths(sends[0]["files"], now_map) if sends else []
    changed_times = [t for t in (_mtime(folder, p) for p in changed) if t is not None]
    all_times = [t for t in (_mtime(folder, p) for p in now_map) if t is not None]
    paths = list(now_map)
    return {
        "location": loc["location_id"], "kind": kind, "name": prepared.name, "harness": loc["harness"],
        "declared_version": declared_version(kind, loc["path"]),
        "file_count": len(prepared.members), "total_bytes": prepared.total_bytes,
        "files": [{"path": p, "size": len(c)} for p, c in prepared.members[:MAX_FILES_LISTED]],
        "license_file": any(_LICENSE_FILE.match(p) for p in paths if "/" not in p),
        "license": declared_license(kind, loc["path"]),
        "grade": str(prepared.lint.get("grade", "")) if prepared.lint else "",
        "cost": {"description_tokens_est": loc["description_tokens_est"], "label": "est."},
        "made_at": _iso(min(all_times)) if all_times else "",
        "changed_files": len(changed), "changed_at": _iso(max(changed_times)) if changed_times else "",
        "sends": [{"submission_id": s["submission_id"], "version": s["version"], "sent_at": s["sent_at"],
                   "hero": s["hero"], "media_submission_id": s["media_submission_id"], "hero_sha": s.get("hero_sha", "")}
                  for s in sends],
        "checks": checks,
    }


def check_summary(refusal_codes: List[str]) -> Tuple[bool, str]:
    if not refusal_codes:
        return True, "clean"
    return False, ", ".join(dict.fromkeys(refusal_codes))[:200] or "refused"

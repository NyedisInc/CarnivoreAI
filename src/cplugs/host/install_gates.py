
from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

from src.cplugs.host import identity
from src.cplugs.host.preview_check import PreviewError, read_preview
from src.cplugs.host.sidecar_manifest import (
    MANIFEST_FILE, SidecarManifest, SidecarManifestError, _views, clean_text, load_sidecar_manifest, sidecar_reasons)
from src.cplugs.sdk import sidecar
from src.cplugs.sdk.manifest import RESERVED_IDS
from src.cplugs.sdk.permission_registry import TIER_CATALOG, risk_of

ALLOWED_SUFFIXES = frozenset({".py", ".json", ".md", ".txt"})
VIEW_SUFFIXES = frozenset({".html", ".css", ".js", ".svg", ".png", ".woff2"})
_NATIVE_MAGIC = (b"\x7fELF", b"MZ", b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")
MAX_MEMBERS = 500
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 3 * 1024 * 1024
_RISK_ORDER = {"high": 0, "medium": 1, "low": 2}

NOT_SAFE = "cplug_not_safe"
TOO_LARGE = "cplug_too_large"
NAME_MISMATCH = "cplug_name_mismatch"
MANIFEST_INVALID = "cplug_manifest_invalid"
SIDECAR_INVALID = "cplug_sidecar_invalid"
FACTS_CHANGED = "cplug_facts_changed"
NOT_ACCEPTED = "cplug_not_accepted"


class CplugGateRefusal(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class CplugFacts(NamedTuple):

    facts: Dict[str, Any]
    sha: str


def _walk(root: Path) -> List[Path]:
    found: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in list(dirnames) + filenames:
            mode = os.lstat(os.path.join(dirpath, name)).st_mode
            if stat.S_ISLNK(mode):
                raise CplugGateRefusal(NOT_SAFE, "a plugin may not contain a symbolic link")
        for name in filenames:
            path = Path(dirpath) / name
            if not stat.S_ISREG(os.lstat(path).st_mode):
                raise CplugGateRefusal(NOT_SAFE, "a plugin may carry regular files only")
            found.append(path)
    return found


def _declared_preview(root: Path) -> str:
    try:
        value = json.loads((root / MANIFEST_FILE).read_text(encoding="utf-8")).get("preview")
    except (OSError, ValueError, AttributeError):
        return ""
    return value if isinstance(value, str) else ""


def _declared_view_files(root: Path) -> frozenset[str]:
    try:
        raw = json.loads((root / MANIFEST_FILE).read_text(encoding="utf-8"))
        views = _views(raw.get("views"), MANIFEST_FILE)
    except (OSError, ValueError, AttributeError, SidecarManifestError):
        return frozenset()
    return frozenset(f"views/{view['name']}/{path}" for view in views for path in view["files"])


def check_files(root: Path) -> List[Path]:
    members = _walk(root)
    if len(members) > MAX_MEMBERS:
        raise CplugGateRefusal(TOO_LARGE, f"a plugin may carry at most {MAX_MEMBERS} files")
    total = 0
    preview = _declared_preview(root)
    view_files = _declared_view_files(root)
    for path in members:
        rel = path.relative_to(root).as_posix()
        is_preview = rel == preview
        if is_preview:
            try:
                read_preview(root, rel)
            except PreviewError as exc:
                raise CplugGateRefusal(NOT_SAFE, f"{rel[:120]}: {exc}") from exc
        elif path.suffix.lower() not in ALLOWED_SUFFIXES and not (rel in view_files and path.suffix.lower() in VIEW_SUFFIXES):
            raise CplugGateRefusal(NOT_SAFE, f"{rel[:120]} is not a file type a plugin may carry")
        info = os.lstat(path)
        if info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            raise CplugGateRefusal(NOT_SAFE, f"{rel[:120]} is executable; a plugin ships plain files")
        if info.st_size > MAX_FILE_BYTES and not is_preview:
            raise CplugGateRefusal(TOO_LARGE, f"{rel[:120]} is over {MAX_FILE_BYTES // 1024} KiB")
        with path.open("rb") as fh:
            header = fh.read(8)
        if header.startswith(_NATIVE_MAGIC) or zipfile.is_zipfile(path):
            raise CplugGateRefusal(NOT_SAFE, f"{rel[:120]} is an executable or archive")
        if rel in view_files and path.suffix.lower() in {".png", ".woff2"}:
            magic = b"\x89PNG\r\n\x1a\n" if path.suffix.lower() == ".png" else b"wOF2"
            if not header.startswith(magic):
                raise CplugGateRefusal(NOT_SAFE, f"{rel[:120]} does not match its declared file type")
        total += info.st_size
    if total > MAX_TOTAL_BYTES:
        raise CplugGateRefusal(TOO_LARGE, f"a plugin may total at most {MAX_TOTAL_BYTES // (1024 * 1024)} MiB")
    return members


def _facts(manifest: SidecarManifest, members: List[Path], root: Path, reasons: Dict[str, str]) -> Dict[str, Any]:
    permissions = [{"name": p, "risk": risk_of(p, TIER_CATALOG), "reason": clean_text(reasons.get(p, ""), 300)} for p in manifest.permissions]
    permissions.sort(key=lambda row: (_RISK_ORDER.get(row["risk"], 3), row["name"]))
    net = manifest.network
    return {
        "id": manifest.id, "name": manifest.name, "description": manifest.description, "version": manifest.version,
        "entry": manifest.entry, "files": len(members), "bytes": sum(os.lstat(p).st_size for p in members),
        "permissions": permissions,
        "tools": [{"name": t["name"], "gate": t["gate"], "description": t["description"], "input_schema": t.get("inputSchema", {})}
                  for t in manifest.tools],
        "network_hosts": [{"host": h.host, "reason": clean_text(h.reason, 300), "methods": list(h.methods), "paths": list(h.paths),
                           "secret": h.auth.secret if h.auth else ""} for h in net.network_hosts],
        "lan_hosts": [{"entry": h.entry, "reason": clean_text(h.reason, 300), "methods": list(h.methods), "paths": list(h.paths)}
                      for h in net.lan_hosts],
        "secrets": [{"name": s.name, "label": clean_text(s.label, 120), "hosts": list(net.secret_hosts(s.name))} for s in net.secrets],
    }


def evaluate(item_id: str, staged_path: Path, publisher_key_id: str = "", pinned_key_id: str = "") -> CplugFacts:
    root = Path(staged_path)
    name = item_id.partition("/")[2]
    members = check_files(root)
    try:
        raw = json.loads((root / MANIFEST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CplugGateRefusal(MANIFEST_INVALID, f"cplug.json cannot be read ({type(exc).__name__})") from exc
    if not isinstance(raw, dict) or raw.get("id") != name:
        raise CplugGateRefusal(NAME_MISMATCH, "the id in cplug.json is not the catalog name of this item")
    try:
        manifest = load_sidecar_manifest(root, name)
    except SidecarManifestError as exc:
        raise CplugGateRefusal(MANIFEST_INVALID, str(exc)[:300]) from exc
    try:
        side = json.loads((root / sidecar.SIDECAR_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        side = None
    reasons = sidecar_reasons(side)
    envelope = replace(manifest, id=item_id, author=side.get("author", "") if isinstance(side, dict) else "",
                       min_app_version=side.get("min_app_version", "") if isinstance(side, dict) else "",
                       icon=side.get("icon", "") if isinstance(side, dict) else "", permission_reasons=reasons)
    report = sidecar.check_plugin(envelope, root)
    if report.status != sidecar.VALID:
        raise CplugGateRefusal(SIDECAR_INVALID, f"carnivore.json is {report.status}: " + "; ".join(report.problems)[:300])
    facts = _facts(manifest, members, root, reasons)
    sha = hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return CplugFacts(facts, sha)


def name_problem(state_dir: Path, name: str, catalog_id: str, shipped_ids: Any) -> Optional[CplugGateRefusal]:
    if not identity.INSTALL_NAME.match(name):
        return CplugGateRefusal("name_invalid", f"an install name must match {identity.INSTALL_NAME.pattern}")
    owner = catalog_id == f"{identity.OWNER_PUBLISHER}/{name}"
    reserved = (frozenset(RESERVED_IDS) | identity.HOST_WORDS) if owner else identity.reserved_names(shipped_ids)
    if name in reserved:
        return CplugGateRefusal("name_reserved", f"{name} is reserved")
    held = identity.lookup(state_dir, name)
    if held is not None and held.catalog_id != catalog_id:
        return CplugGateRefusal("name_taken", f"{name} is held by another plugin")
    return None


def check_consent(consent: Any, facts: CplugFacts) -> None:
    if consent is None or not getattr(consent, "cplug_accepted", False):
        raise CplugGateRefusal(NOT_ACCEPTED, "the plugin's permissions and tools must be read and accepted first")
    if getattr(consent, "cplug_facts_sha", "") != facts.sha:
        raise CplugGateRefusal(FACTS_CHANGED, "what this plugin declares changed since the sheet; show it again")


from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Collection, Dict, List, NamedTuple, Optional

from src.plugins.host import dependencies, identity
from src.plugins.host.plugin_manifest import SidecarManifest, SidecarManifestError, load_sidecar_manifest
from src.plugins.host.preview_check import PreviewError, read_icon, read_preview
from src.plugins.sdk import api_contract
from src.plugins.sdk._manifest_v2_sections import _parse_views
from src.plugins.sdk.cplug_validate import (
    ALLOWED_SUFFIXES as ALLOWED_SUFFIXES,
    MAX_FILE_BYTES as MAX_FILE_BYTES,
    MAX_MEMBERS as MAX_MEMBERS,
    MAX_TOTAL_BYTES as MAX_TOTAL_BYTES,
    V2_ALLOWED_SUFFIXES as V2_ALLOWED_SUFFIXES,
    VIEW_SUFFIXES as VIEW_SUFFIXES,
    is_allowed_declared_binary_path as is_allowed_declared_binary_path,
    validate_v2_folder_files,
)
from src.plugins.sdk.manifest_v2 import ManifestV2Error, clean_text, has_v2_manifest, load_raw_v2
from src.plugins.sdk.permission_registry import TIER_CATALOG, risk_of

_RISK_ORDER = {"high": 0, "medium": 1, "low": 2}

NOT_SAFE = "cplug_not_safe"
TOO_LARGE = "cplug_too_large"
NAME_MISMATCH = "cplug_name_mismatch"
MANIFEST_INVALID = "cplug_manifest_invalid"
SIDECAR_INVALID = "cplug_sidecar_invalid"
FACTS_CHANGED = "cplug_facts_changed"
NOT_ACCEPTED = "cplug_not_accepted"
API_VERSION_UNSUPPORTED = "cplug_api_version_unsupported"


class CplugGateRefusal(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class CplugFacts(NamedTuple):

    facts: Dict[str, Any]
    sha: str


def _declared_preview(root: Path) -> str:
    if not has_v2_manifest(root):
        return ""
    try:
        raw, _ = load_raw_v2(root)
        value = raw.get("preview")
    except (OSError, ValueError, AttributeError, ManifestV2Error):
        return ""
    return value if isinstance(value, str) else ""


def _declared_view_files(root: Path) -> frozenset[str]:
    if not has_v2_manifest(root):
        return frozenset()
    try:
        raw, fname = load_raw_v2(root)
        ui = raw.get("ui")
        views = _parse_views(ui.get("views") if isinstance(ui, dict) else None, fname)
    except (OSError, ValueError, AttributeError, ManifestV2Error):
        return frozenset()
    return frozenset(f"views/{view['name']}/{path}" for view in views for path in view["files"])


def _v2_declared_binary(root: Path) -> str:
    try:
        raw, _fname = load_raw_v2(root)
    except (OSError, ValueError, AttributeError, ManifestV2Error):
        return ""
    run = raw.get("run")
    if not isinstance(run, dict):
        return ""
    cmd = run.get("cmd")
    if not isinstance(cmd, list) or not cmd or not isinstance(cmd[0], str):
        return ""
    preview = raw.get("preview") if isinstance(raw.get("preview"), str) else ""
    return is_allowed_declared_binary_path(cmd[0], preview=preview)


def _declared_icon_file(root: Path) -> str:
    if not has_v2_manifest(root):
        return ""
    try:
        raw, _ = load_raw_v2(root)
        value = raw.get("icon_file")
    except (OSError, ValueError, AttributeError, ManifestV2Error):
        return ""
    return value if isinstance(value, str) else ""


def check_files(root: Path) -> List[Path]:
    is_v2 = has_v2_manifest(root)
    allowed_suffixes = V2_ALLOWED_SUFFIXES if is_v2 else ALLOWED_SUFFIXES
    declared_binary = _v2_declared_binary(root) if is_v2 else ""
    preview = _declared_preview(root)
    icon_file = _declared_icon_file(root)
    view_files = _declared_view_files(root)

    def _preview_err(_path: Path, rel: str) -> Optional[str]:
        try:
            read_preview(root, rel)
        except PreviewError as exc:
            return str(exc)
        return None

    def _icon_err(_path: Path, rel: str) -> Optional[str]:
        try:
            read_icon(root, rel)
        except PreviewError as exc:
            return str(exc)
        return None

    members, errors = validate_v2_folder_files(
        root,
        allowed_suffixes=allowed_suffixes,
        allow_shell_exec=is_v2,
        declared_binary=declared_binary,
        preview=preview,
        icon_file=icon_file,
        view_files=view_files,
        check_exec=True,
        check_magic=True,
        forbid_node_pkg=not is_v2,
        preview_checker=_preview_err,
        icon_checker=_icon_err,
        stop_on_first=True,
    )
    if errors:
        code, _rel, detail = errors[0]
        refusal_code = TOO_LARGE if code == "cplug_too_large" else NOT_SAFE
        raise CplugGateRefusal(refusal_code, detail)
    return members


def _facts(manifest: SidecarManifest, members: List[Path], root: Path, reasons: Dict[str, str]) -> Dict[str, Any]:
    permissions = [{"name": p, "risk": risk_of(p, TIER_CATALOG), "reason": clean_text(reasons.get(p, ""), 300)} for p in manifest.permissions]
    permissions.sort(key=lambda row: (_RISK_ORDER.get(row["risk"], 3), row["name"]))
    net = manifest.network
    out: Dict[str, Any] = {
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
    blockers = dependencies.enable_blockers(manifest)
    if blockers:
        out["unmet_requirements"] = blockers
    return out


def evaluate(item_id: str, staged_path: Path, publisher_key_id: str = "", pinned_key_id: str = "") -> CplugFacts:
    root = Path(staged_path)
    name = item_id.partition("/")[2]
    members = check_files(root)
    if not has_v2_manifest(root):
        raise CplugGateRefusal(MANIFEST_INVALID, "plugin must carry carnivore.toml or schema = 2 carnivore.json")
    try:
        raw, _fname = load_raw_v2(root)
    except (ManifestV2Error, FileNotFoundError, OSError, ValueError) as exc:
        raise CplugGateRefusal(MANIFEST_INVALID, str(exc)[:300]) from exc
    if raw.get("id") != name:
        raise CplugGateRefusal(NAME_MISMATCH, "the id in the manifest is not the catalog name of this item")
    if "tier" in raw and raw.get("tier") != TIER_CATALOG:
        raise CplugGateRefusal(MANIFEST_INVALID, "catalog plugins may not declare a non-catalog tier")
    if raw.get("default_enabled") is True:
        raise CplugGateRefusal(MANIFEST_INVALID, "catalog plugins may not declare default_enabled = true")
    try:
        api_contract.require_served(raw)
    except api_contract.ApiVersionUnsupported as exc:
        raise CplugGateRefusal(API_VERSION_UNSUPPORTED, str(exc)) from exc
    try:
        manifest = load_sidecar_manifest(root, name)
    except SidecarManifestError as exc:
        raise CplugGateRefusal(MANIFEST_INVALID, str(exc)[:300]) from exc
    if manifest.tier != TIER_CATALOG or manifest.default_enabled:
        raise CplugGateRefusal(MANIFEST_INVALID, "catalog plugins must have catalog tier and default_enabled = false")
    reasons = dict(manifest.permission_reasons)
    facts = _facts(manifest, members, root, reasons)
    sha = hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return CplugFacts(facts, sha)


def name_problem(state_dir: Path, name: str, catalog_id: str, shipped_ids: Any, *, renamed_ids: Collection[str] = ()) -> Optional[CplugGateRefusal]:
    if not identity.INSTALL_NAME.match(name):
        return CplugGateRefusal("name_invalid", f"an install name must match {identity.INSTALL_NAME.pattern}")
    try:
        identity.check_catalog_id(catalog_id, name, shipped_ids)
    except identity.InstallRefused as exc:
        return CplugGateRefusal(exc.code, str(exc))
    owner = catalog_id == f"{identity.OWNER_PUBLISHER}/{name}"
    reserved = identity.owner_refused(renamed_ids) if owner else identity.reserved_names(shipped_ids)
    if name in reserved:
        return CplugGateRefusal("name_reserved", f"{name} is reserved")
    held = identity.lookup(state_dir, name)
    if held is not None and held.catalog_id != catalog_id:
        return CplugGateRefusal("name_taken", f"the name {name} belongs to {held.catalog_id}; rename yours")
    return None


def check_consent(consent: Any, facts: CplugFacts) -> None:
    if consent is None or not getattr(consent, "cplug_accepted", False):
        raise CplugGateRefusal(NOT_ACCEPTED, "the plugin's permissions and tools must be read and accepted first")
    if getattr(consent, "cplug_facts_sha", "") != facts.sha:
        raise CplugGateRefusal(FACTS_CHANGED, "what this plugin declares changed since the sheet; show it again")

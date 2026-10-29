
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import structlog

from src.cplugs.sdk.data_decl import problems_in as data_problems, settings_fields_of
from src.cplugs.sdk.manifest import SIDECAR_FILE, Manifest
from src.cplugs.sdk.schema_check import SchemaSet

logger = structlog.get_logger()

SIDECAR_NAME = SIDECAR_FILE
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "extensions"
ENFORCEMENT = "warn"
PENDING: Mapping[str, str] = {}

VALID, MISSING, INVALID, DISAGREES = "valid", "missing", "invalid", "disagrees"


class SidecarError(RuntimeError):
    pass


@dataclass(frozen=True)
class SidecarReport:

    plugin_id: str
    status: str
    problems: Tuple[str, ...] = ()
    name: str = ""


@lru_cache(maxsize=1)
def schemas() -> SchemaSet:
    return SchemaSet.load(SCHEMA_DIR)


def validate_document(document: Any) -> List[str]:
    if not isinstance(document, dict):
        return ["$: a sidecar must be an object"]
    kind = document.get("kind")
    name = f"{kind}.schema.json"
    if not isinstance(kind, str) or name not in schemas().documents:
        return [f"$.kind: {kind!r} is not a kind of the contract"]
    return schemas().validate(name, document)


def _agreement(sidecar: Mapping[str, Any], manifest: Manifest) -> List[str]:
    problems: List[str] = []
    for key, mine in (("id", manifest.id), ("version", manifest.version), ("author", manifest.author),
                      ("min_app_version", manifest.min_app_version), ("tier", manifest.tier), ("icon", manifest.icon)):
        if sidecar.get(key) != mine:
            problems.append(f"{key}: sidecar says {sidecar.get(key)!r}, cplug.json says {mine!r}")
    if sidecar.get("default_enabled") != manifest.default_enabled:
        problems.append(f"default_enabled: sidecar says {sidecar.get('default_enabled')!r}, cplug.json says {manifest.default_enabled!r}")
    perms = sidecar.get("permissions", [])
    names = tuple(p.get("name") for p in perms if isinstance(p, dict))
    if names != manifest.permissions:
        problems.append(f"permissions: sidecar lists {list(names)}, cplug.json asks {list(manifest.permissions)}")
    reasons = {p["name"]: p["reason"] for p in perms if isinstance(p, dict) and "reason" in p}
    if reasons != dict(manifest.permission_reasons):
        problems.append("permission reasons differ between the sidecar and cplug.json")
    wanted = sorted([("cplug", r) for r in manifest.requires] + [("core", r) for r in manifest.requires_core])
    have = sorted((r.get("kind"), r.get("id")) for r in sidecar.get("requires", []) if isinstance(r, dict))
    if have != wanted:
        problems.append(f"requires: sidecar lists {have}, cplug.json needs {wanted}")
    if {k: v for k, v in sidecar.get("owns", {}).items() if v} != {k: v for k, v in manifest.owns.as_wire().items() if v}:
        problems.append("owns: the sidecar and cplug.json declare different things")
    return problems


def check_plugin(manifest: Manifest, plugin_dir: Path) -> SidecarReport:
    path = plugin_dir / SIDECAR_NAME
    if not path.is_file():
        return SidecarReport(manifest.id, MISSING, (f"{path.name} is missing",))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return SidecarReport(manifest.id, INVALID, (f"unreadable ({type(exc).__name__})",))
    errors = validate_document(raw)
    if not errors and raw.get("kind") != "cplug":
        errors = [f"$.kind: a plugin's sidecar must say cplug, not {raw.get('kind')!r}"]
    if not errors:
        errors = data_problems(raw.get("data", []), settings_fields_of(manifest.settings_schema))
    if errors:
        return SidecarReport(manifest.id, INVALID, tuple(errors))
    disagreements = _agreement(raw, manifest)
    if disagreements:
        return SidecarReport(manifest.id, DISAGREES, tuple(disagreements), raw["name"])
    return SidecarReport(manifest.id, VALID, (), raw["name"])


def audit_ship_list(manifests: Iterable[Manifest], root: Path, enforcement: Optional[str] = None) -> Dict[str, SidecarReport]:
    mode = enforcement or ENFORCEMENT
    reports: Dict[str, SidecarReport] = {}
    for manifest in manifests:
        report = check_plugin(manifest, root / manifest.id)
        reports[manifest.id] = report
        if report.status != VALID:
            logger.warning("cplug_sidecar_" + report.status, cplug=manifest.id, problems=list(report.problems),
                           pending=PENDING.get(manifest.id), enforcement=mode)
    if mode == "refuse":
        bad = {k: r for k, r in reports.items() if r.status != VALID}
        if bad:
            raise SidecarError("; ".join(f"{k}: {r.status} ({'; '.join(r.problems)})" for k, r in sorted(bad.items())))
    return reports



from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List

from src.core.catalog import plugin_pack
from src.plugins.host.sidecar_manifest import SidecarManifestError, parse_sidecar_manifest
from src.plugins.host import identity
from src.plugins.sdk import api_contract
from src.plugins.sdk.manifest import ID_PATTERN
from src.plugins.sdk.schema_check import SchemaError, SchemaSet

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "src" / "schemas" / "extensions"
SECRETISH = re.compile(r"(token|passw(or)?d|passwd|api[_-]?key|secret|credential|bearer)", re.IGNORECASE)
SCHEMA_PUBLISHER = "author"


def name_problem(name: str) -> str:
    shipped = [p.parent.name for p in (SCHEMA_DIR.parents[1] / "plugins").glob("*/cplug.json")]
    if not ID_PATTERN.match(name):
        return f"{name!r} must match {ID_PATTERN.pattern} (lowercase letters and digits, no hyphen)"
    if name in identity.reserved_names(shipped):
        return f"{name} is reserved (a first-party feature or a host word)"
    return ""


@dataclass
class CheckReport:

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    packed: Any = None

    @property
    def ok(self) -> bool:
        return not self.errors


def _read_json(path: Path, errors: List[str]) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"{path.name} is missing")
        return {}
    except (OSError, ValueError) as exc:
        errors.append(f"{path.name} cannot be read as json ({type(exc).__name__})")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.name} must hold a json object")
        return {}
    return value


def secretish_names(node: Any, where: str = "$") -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and SECRETISH.search(key):
                yield f"{where}.{key}"
            yield from secretish_names(value, f"{where}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from secretish_names(item, f"{where}[{i}]")


def _secret_warnings(runtime: Dict[str, Any], report: CheckReport) -> None:
    for path in secretish_names([t.get("inputSchema") for t in runtime.get("tools", []) if isinstance(t, dict)], "tools"):
        report.warnings.append(f"{path} looks like a credential: do not take it as an argument or setting; declare it under secrets and read it through the Keychain secret API")


def _check_schema(carnivore: Dict[str, Any], report: CheckReport) -> None:
    doc = dict(carnivore, tier="catalog", id=f"{SCHEMA_PUBLISHER}/{str(carnivore.get('id', '')).rpartition('/')[2]}")
    try:
        problems = SchemaSet.load(SCHEMA_DIR).validate("warez/cplug.schema.json", doc)
    except SchemaError as exc:
        report.errors.append(f"the schema set cannot be read: {exc}")
        return
    report.errors.extend(f"carnivore.json: {p}" for p in problems)


def check_folder(folder: Path) -> CheckReport:
    report = CheckReport()
    authored = _read_json(folder / plugin_pack.CARNIVORE_FILE, report.errors)
    if not authored:
        return report
    name = str(authored.get("id", "")).rpartition("/")[2]
    if name_problem(name):
        report.errors.append(f"id: {name_problem(name)}")
    try:
        if plugin_pack.is_authored(authored):
            report.packed = plugin_pack.pack_manifest(authored)
        else:
            runtime = _read_json(folder / plugin_pack.CPLUG_FILE, report.errors)
            report.packed = plugin_pack.check_pair(authored, runtime) if runtime else None
    except plugin_pack.PackError as exc:
        report.errors.append(str(exc))
    if report.packed is None:
        return report
    report.warnings.extend(report.packed.notes)
    try:
        api_contract.require_served(report.packed.carnivore)
    except api_contract.ApiVersionUnsupported as exc:
        report.errors.append(str(exc))
    _check_schema(report.packed.carnivore, report)
    try:
        manifest = parse_sidecar_manifest(report.packed.cplug, name, "0" * 64)
    except SidecarManifestError as exc:
        report.errors.append(str(exc))
    else:
        if not (folder / manifest.entry).is_file():
            report.errors.append(f"entry {manifest.entry} is not a file in the folder")
    _secret_warnings(report.packed.cplug, report)
    return report

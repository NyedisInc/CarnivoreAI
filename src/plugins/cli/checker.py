
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from src.core import message_model_secrets
from src.plugins.cli import templates
from src.plugins.host import install_gates
from src.plugins.host.plugin_manifest import SidecarManifestError, validate_v2_files
from src.plugins.host.sideload_copy import DEV_SKIP_DIRS
from src.plugins.sdk import cplug_validate
from src.plugins.sdk.manifest_v2 import ManifestV2, ManifestV2Error, has_v2_manifest, load_manifest_v2

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "extensions"
SECRETISH = re.compile(r"(token|passw(or)?d|passwd|api[_-]?key|secret|credential|bearer)", re.IGNORECASE)
SCHEMA_PUBLISHER = "author"
_SOURCE_DETECTORS = tuple(
    d for d in message_model_secrets.ALL_DETECTORS if d != message_model_secrets.DETECTOR_HIGH_ENTROPY_ASSIGNMENT
)
_SCAN_EXTS = frozenset({".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".sh", ".bash", ".json", ".toml", ".yaml", ".yml", ".html", ".css", ".md", ".txt"})


def name_problem(name: str) -> str:
    return templates.name_problem(name)


@dataclass
class CheckReport:

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    manifest_v2: Optional[ManifestV2] = None

    @property
    def ok(self) -> bool:
        return not self.errors


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
        report.warnings.append(
            f"{path} looks like a credential: do not take it as an argument or setting; declare it under secrets and read it through the Keychain secret API"
        )


def _check_v2_tree(folder: Path, manifest_v2: ManifestV2, report: CheckReport) -> None:
    view_files = frozenset(f"views/{v['name']}/{p}" for v in manifest_v2.views for p in v.get("files", ()))
    declared_bin = (
        cplug_validate.is_allowed_declared_binary_path(manifest_v2.run_cmd[0], preview=manifest_v2.preview)
        if manifest_v2.run_cmd
        else ""
    )
    kept, errors = cplug_validate.validate_v2_folder_files(
        folder,
        skip_dirs=DEV_SKIP_DIRS,
        ignore_junk=True,
        allowed_suffixes=install_gates.V2_ALLOWED_SUFFIXES,
        allow_shell_exec=True,
        declared_binary=declared_bin,
        preview=manifest_v2.preview,
        view_files=view_files,
        check_exec=False,
        check_magic=True,
        stop_on_first=False,
    )
    bad_rels = {rel for _code, rel, _detail in errors if rel}
    for _code, _rel, detail in errors:
        report.errors.append(detail)
    for path in kept:
        rel = path.relative_to(folder).as_posix()
        if rel in bad_rels or path.suffix.lower() not in _SCAN_EXTS:
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            report.errors.append(f"{rel}: unreadable ({type(exc).__name__})")
            continue
        found = sorted({
            f.detector
            for f in message_model_secrets.scan_text(raw.decode("utf-8", errors="replace"), detectors=_SOURCE_DETECTORS)
        })
        if found:
            report.errors.append(f"{rel}: potential credential detected ({', '.join(found)})")


def check_folder(folder: Path) -> CheckReport:
    report = CheckReport()
    if not folder.is_dir():
        report.errors.append(f"{folder} is not a directory")
        return report

    if not has_v2_manifest(folder):
        report.errors.append("carnivore.toml (or schema = 2 carnivore.json) is missing")
        return report

    try:
        manifest_v2 = load_manifest_v2(folder, allow_tier_override=True)
    except (ManifestV2Error, FileNotFoundError, OSError, ValueError) as exc:
        report.errors.append(str(exc))
        return report
    report.manifest_v2 = manifest_v2
    prob = name_problem(manifest_v2.id)
    if prob:
        report.errors.append(f"id: {prob}")
    try:
        validate_v2_files(folder, manifest_v2, manifest_v2.id)
    except SidecarManifestError as exc:
        report.errors.append(str(exc))
    _check_v2_tree(folder, manifest_v2, report)
    _secret_warnings({"tools": list(manifest_v2.tools)}, report)
    return report


from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from src.plugins.host.preview_check import PreviewError, read_icon, read_preview, read_screenshot
from src.plugins.host.sidecar_page import parse_page
from src.plugins.runtime.integrity import IntegrityError, tree_digest
from src.plugins.sdk.manifest import Ownership, Surfaces
from src.plugins.sdk.manifest_v2 import (
    ManifestV2,
    ManifestV2Error,
    TIER_LOCAL,
    has_v2_manifest,
    load_manifest_v2,
)
from src.plugins.sdk.network import NetworkDecl
from src.plugins.sdk.permission_registry import TIER_CATALOG


class SidecarManifestError(ValueError):
    pass


@dataclass(frozen=True)
class SidecarManifest:

    id: str
    name: str
    description: str
    version: str
    entry: str
    tools: Tuple[Mapping[str, Any], ...]
    permissions: Tuple[str, ...]
    network: NetworkDecl
    code_digest: str
    tier: str = TIER_CATALOG
    default_enabled: bool = False
    name_key: str = ""
    description_key: str = ""
    icon: str = "plug"
    owns: Ownership = field(default_factory=Ownership)
    author: str = ""
    min_app_version: str = ""
    surfaces: Surfaces = field(default_factory=Surfaces)
    settings_schema: Mapping[str, Any] = field(default_factory=lambda: {"version": 1, "fields": {}})
    settings_aliases: Mapping[str, str] = field(default_factory=dict)
    requires: Tuple[str, ...] = ()
    requires_core: Tuple[str, ...] = ()
    permission_reasons: Mapping[str, str] = field(default_factory=dict)
    ai_features: Mapping[str, Any] = field(default_factory=dict)
    widgets: Mapping[str, Any] = field(default_factory=dict)
    legacy_ids: Mapping[str, str] = field(default_factory=dict)
    mcp_tool_aliases: Mapping[str, str] = field(default_factory=dict)
    data: Tuple[Any, ...] = ()
    routes: Tuple[str, ...] = ()
    subscriptions: Tuple[str, ...] = ()
    views: Tuple[Mapping[str, Any], ...] = ()
    trust: str = ""
    preview: str = ""
    screenshots: Tuple[str, ...] = ()
    icon_file: str = ""
    page: Optional[Mapping[str, Any]] = None
    page_problem: str = ""
    topics: Tuple[str, ...] = ()
    schema_version: int = 2
    kind: str = "plugin"
    tier0: bool = False
    run_cmd: Tuple[str, ...] = ()
    run_mode: str = "rpc"
    timers: Mapping[str, int] = field(default_factory=dict)
    webhooks: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    channels: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    macros: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    harnesses: Tuple[str, ...] = ()
    events_emit: Tuple[str, ...] = ()
    events_allowed: Tuple[str, ...] = ()
    services_provides: Tuple[Mapping[str, Any], ...] = ()
    services_consumes: Tuple[str, ...] = ()
    ui_contribute: Mapping[str, Any] = field(default_factory=dict)
    ui_meta: Mapping[str, Any] = field(default_factory=dict)
    ui_slots: Tuple[str, ...] = ()


def from_manifest_v2(v2: ManifestV2, code_digest: str, *, allow_local: bool = False) -> SidecarManifest:
    allowed_tiers = (TIER_CATALOG, TIER_LOCAL) if allow_local else (TIER_CATALOG,)
    if v2.tier not in allowed_tiers:
        raise SidecarManifestError(f"cplug {v2.id}: sidecar manifest tier must be {TIER_CATALOG!r}, got {v2.tier!r}")
    if v2.tier == TIER_CATALOG and v2.default_enabled is True:
        raise SidecarManifestError(f"cplug {v2.id}: catalog plugin cannot set default_enabled = true")
    page, page_problem = parse_page(v2.page, v2.views)
    subscriptions = tuple(dict.fromkeys([*v2.events_on, *(f"webhook.{h}" for h in v2.webhooks)]))
    return SidecarManifest(
        id=v2.id,
        name=v2.name,
        description=v2.description,
        version=v2.version,
        entry=v2.entry,
        tools=v2.tools,
        permissions=v2.permissions,
        network=v2.network,
        code_digest=code_digest,
        tier=v2.tier,
        default_enabled=False,
        icon=v2.icon,
        owns=v2.owns,
        author=v2.author,
        min_app_version=v2.min_app_version,
        settings_schema=v2.settings_schema,
        requires=v2.requires,
        requires_core=v2.requires_core,
        permission_reasons=v2.permission_reasons,
        ai_features=v2.ai_features,
        data=v2.data or (),
        routes=v2.routes,
        subscriptions=subscriptions,
        views=v2.views,
        trust=v2.trust,
        preview=v2.preview,
        screenshots=v2.screenshots,
        icon_file=v2.icon_file,
        page=page,
        page_problem=page_problem,
        topics=v2.topics,
        schema_version=2,
        kind=v2.kind,
        tier0=v2.tier0,
        run_cmd=v2.run_cmd,
        run_mode=v2.run_mode,
        timers=v2.timers,
        webhooks=v2.webhooks,
        channels=v2.channels,
        macros=v2.macros,
        harnesses=v2.harnesses,
        events_emit=v2.events_emit,
        events_allowed=v2.events_allowed,
        services_provides=v2.services_provides,
        services_consumes=v2.services_consumes,
        ui_contribute=v2.ui_contribute,
        ui_meta=v2.ui_meta,
        ui_slots=v2.ui_slots,
    )


def validate_v2_files(code_root: Path, v2: ManifestV2, item_name: str) -> None:
    root = Path(code_root)
    if not v2.tier0 and v2.run_cmd:
        cmd0 = v2.run_cmd[0]
        exe = Path(cmd0).name.lower()
        if not cmd0.startswith("/") and (cmd0.startswith("./") or "/" in cmd0 or exe not in ("python", "python3", "uv", "node", "bun", "bash", "sh")):
            bin_path = root / cmd0
            if not bin_path.is_file() or bin_path.is_symlink():
                raise SidecarManifestError(f"cplug {item_name}: executable {cmd0!r} is not a file in the code folder")
        if v2.entry and v2.entry != cmd0:
            entry = root / v2.entry
            if not entry.is_file() or entry.is_symlink():
                raise SidecarManifestError(f"cplug {item_name}: entry is not a file in the code folder")

    for ui_key in ("widget", "sidebar_tab"):
        decl = v2.ui_meta.get(ui_key) if isinstance(v2.ui_meta, Mapping) else None
        if isinstance(decl, Mapping) and ("document" in decl or "ui_file" in decl):
            from src.plugins.host import ui_doc  # noqa: PLC0415

            doc = decl.get("document")
            if "ui_file" in decl:
                ui_path = root / str(decl["ui_file"])
                if not ui_path.is_file() or ui_path.is_symlink():
                    raise SidecarManifestError(f"cplug {item_name}: {ui_key}.ui_file {decl['ui_file']!r} is missing")
                try:
                    doc = json.loads(ui_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise SidecarManifestError(f"cplug {item_name}: {ui_key}.ui_file unreadable ({type(exc).__name__})") from exc
            if doc is not None:
                try:
                    ui_doc.validate(doc, routes=v2.routes, tools=[t.get("name") for t in v2.tools if isinstance(t, Mapping) and "name" in t])
                except ui_doc.UiDocError as exc:
                    raise SidecarManifestError(f"cplug {item_name}: invalid {ui_key} ui_doc ({exc.code} at {exc.path})") from exc

    if v2.harnesses:
        from src.core.agent_manifests import engine as harness_engine  # noqa: PLC0415

        for rel in v2.harnesses:
            hpath = root / rel
            if not hpath.is_file() or hpath.is_symlink():
                raise SidecarManifestError(f"cplug {item_name}: harness {rel!r} is missing")
            try:
                harness_engine.parse_manifest(hpath.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, harness_engine.RuleFileError, KeyError, ValueError, TypeError, AttributeError, RecursionError, OverflowError) as exc:
                raise SidecarManifestError(f"cplug {item_name}: harness {rel!r} invalid ({exc})") from exc


def load_sidecar_manifest(code_root: Path, item_name: str, *, allow_local: bool = False) -> SidecarManifest:
    try:
        digest = tree_digest(code_root)
    except (IntegrityError, OSError, ValueError) as exc:
        raise SidecarManifestError(f"cplug {item_name}: the code folder cannot be read ({type(exc).__name__})") from exc
    if not has_v2_manifest(code_root):
        raise SidecarManifestError(f"cplug {item_name}: plugin must declare carnivore.toml or schema = 2 carnivore.json")
    try:
        if allow_local:
            v2 = load_manifest_v2(
                code_root,
                expected_id=item_name,
                tier=TIER_CATALOG,
                expected_tier=None,
                allow_tier_override=True,
            )
        else:
            v2 = load_manifest_v2(code_root, expected_id=item_name, expected_tier=TIER_CATALOG)
    except (ManifestV2Error, FileNotFoundError, OSError, ValueError) as exc:
        raise SidecarManifestError(f"cplug {item_name}: {exc}") from exc
    manifest = from_manifest_v2(v2, digest, allow_local=allow_local)
    validate_v2_files(code_root, v2, item_name)
    if manifest.preview:
        try:
            read_preview(code_root, manifest.preview)
        except PreviewError as exc:
            raise SidecarManifestError(f"cplug {item_name}: {exc}") from exc
    for rel_shot in manifest.screenshots:
        try:
            read_screenshot(code_root, rel_shot)
        except PreviewError as exc:
            raise SidecarManifestError(f"cplug {item_name}: {exc}") from exc
    if manifest.icon_file:
        try:
            read_icon(code_root, manifest.icon_file)
        except PreviewError as exc:
            raise SidecarManifestError(f"cplug {item_name}: {exc}") from exc
    return manifest

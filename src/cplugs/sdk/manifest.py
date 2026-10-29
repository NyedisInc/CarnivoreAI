
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import structlog

from src.cplugs.sdk.core_features import CORE_FEATURES
from src.cplugs.sdk.ai_features import AiFeature, AiFeatureError, parse_ai_features
from src.cplugs.sdk.data_decl import DataDecl, DataDeclError, parse_data, settings_fields_of
from src.cplugs.sdk.ownership import Ownership, OwnershipError, parse_ownership
from src.cplugs.sdk.network import NetworkDecl, NetworkDeclError, parse_network
from src.cplugs.sdk.permission_registry import MANIFEST_TIERS, is_declarable, may_ask, tier_may_ask_text
from src.cplugs.sdk.tool_families import TOOL_FAMILIES, family_prefix

logger = structlog.get_logger()

SIDECAR_FILE = "carnivore.json"
ID_PATTERN = re.compile(r"^[a-z][a-z0-9]{1,23}$")
RESERVED_IDS = frozenset({
    "core", "cplug", "cplugs", "plugin", "plugins", "app", "session", "sessions", "projects", "pipeline", "log", "board", "ai",
    "approval", "auto", "usage", "alerts", "conversation", "transcript", "perf", "self", "whoami",
})
TIERS = MANIFEST_TIERS
SURFACE_KEYS = frozenset({"routes", "mcp_tools", "topics", "tabs", "page_section", "page_section_label_key", "page_section_icon", "widgets", "plugins", "menu_links", "feed", "storage"})
_TOP_KEYS = frozenset({
    "schema", "id", "name_key", "description_key", "version", "icon", "author", "min_app_version", "tier",
    "default_enabled", "permissions", "surfaces", "widgets", "settings_schema", "css_prefix", "requires", "ai_features",
    "network_hosts", "lan_hosts", "secrets", "permission_reasons", "requires_core", "owns", "tool_family",
    "mcp_tool_aliases", "settings_aliases", "legacy_ids",
})
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_CSS = re.compile(r"^[a-z][a-z0-9-]{1,23}$")


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Surfaces:

    routes: bool = False
    mcp_tools: Tuple[str, ...] = ()
    topics: Tuple[str, ...] = ()
    tabs: Tuple[str, ...] = ()
    widgets: Tuple[str, ...] = ()
    plugins: Tuple[str, ...] = ()
    menu_links: Tuple[str, ...] = ()
    feed: bool = False
    storage: bool = False
    page_section: str = ""
    page_section_label_key: str = ""
    page_section_icon: str = ""

    def as_wire(self) -> Dict[str, Any]:
        return {"routes": self.routes, "mcp_tools": list(self.mcp_tools), "topics": list(self.topics),
                "tabs": list(self.tabs), "widgets": list(self.widgets), "plugins": list(self.plugins),
                "menu_links": list(self.menu_links), "feed": self.feed, "storage": self.storage,
                "page_section": self.page_section, "page_section_label_key": self.page_section_label_key,
                "page_section_icon": self.page_section_icon}


@dataclass(frozen=True)
class Manifest:

    id: str
    name_key: str
    description_key: str
    version: str
    icon: str
    author: str
    min_app_version: str
    tier: str
    default_enabled: Optional[bool]
    permissions: Tuple[str, ...]
    surfaces: Surfaces
    settings_schema: Mapping[str, Any] = field(default_factory=lambda: {"version": 1, "fields": {}})
    css_prefix: str = ""
    widgets: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    requires: Tuple[str, ...] = ()
    requires_core: Tuple[str, ...] = ()
    ai_features: Mapping[str, AiFeature] = field(default_factory=dict)
    network: NetworkDecl = field(default_factory=NetworkDecl)
    permission_reasons: Mapping[str, str] = field(default_factory=dict)
    owns: Ownership = field(default_factory=Ownership)
    tool_family: str = ""
    mcp_tool_aliases: Mapping[str, str] = field(default_factory=dict)
    settings_aliases: Mapping[str, str] = field(default_factory=dict)
    legacy_ids: Mapping[str, str] = field(default_factory=dict)
    data: Optional[Tuple[DataDecl, ...]] = None
    code_digest: str = ""


def _semver(value: Any, where: str) -> Tuple[int, int, int]:
    if not isinstance(value, str) or not _SEMVER.match(value):
        raise ManifestError(f"{where} must be a semver string x.y.z")
    major, minor, patch = (int(p) for p in value.split("."))
    return major, minor, patch


def version_tuple(value: str) -> Tuple[int, int, int]:
    return _semver(value.split("-", 1)[0], "version")


def _names(raw: Mapping[str, Any], key: str, where: str) -> Tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ManifestError(f"{where}.{key} must be a list of names")
    if len(set(value)) != len(value):
        raise ManifestError(f"{where}.{key} names one entry twice")
    return tuple(value)


def _tool_family(cplug_id: str, raw: Any) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str) or raw not in TOOL_FAMILIES:
        raise ManifestError(f"{cplug_id}: tool_family must be one of {sorted(TOOL_FAMILIES)}")
    if cplug_id not in TOOL_FAMILIES[raw]:
        raise ManifestError(f"{cplug_id}: tool_family {raw} is not granted to {cplug_id} (sdk/tool_families.py)")
    return raw


def _tool_aliases(cplug_id: str, raw: Any, surfaces: Surfaces) -> Dict[str, str]:
    where = f"{cplug_id}: mcp_tool_aliases"
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise ManifestError(f"{where} must map an old tool name to a current one")
    for old, current in raw.items():
        if not old.startswith(f"{cplug_id}_") or old == f"{cplug_id}_" or not re.match(r"^[a-z][a-z0-9_]*$", old):
            raise ManifestError(f"{where}: {old} must be named {cplug_id}_<verb>")
        if current not in surfaces.mcp_tools:
            raise ManifestError(f"{where}: {old} points at {current}, which is not in surfaces.mcp_tools")
        if old in surfaces.mcp_tools:
            raise ManifestError(f"{where}: {old} is also a current tool name in surfaces.mcp_tools")
    if len(set(raw.values())) != len(raw):
        raise ManifestError(f"{where}: two old names point at one current name")
    return dict(raw)


def _settings_aliases(cplug_id: str, raw: Any, settings_schema: Mapping[str, Any]) -> Dict[str, str]:
    where = f"{cplug_id}: settings_aliases"
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise ManifestError(f"{where} must map a current setting key to the retired key it replaced")
    fields = settings_schema.get("fields", {}) if isinstance(settings_schema, Mapping) else {}
    for current, retired in raw.items():
        if current not in fields:
            raise ManifestError(f"{where}: {current} is not in settings_schema.fields")
        if retired in fields:
            raise ManifestError(f"{where}: {retired} is also a current setting key")
    if len(set(raw.values())) != len(raw):
        raise ManifestError(f"{where}: two current keys name one retired key")
    return dict(raw)


def _legacy_ids(cplug_id: str, raw: Any, settings_schema: Mapping[str, Any]) -> Dict[str, str]:
    where = f"{cplug_id}: legacy_ids"
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise ManifestError(f"{where} must map a retired plugin id to the setting that carries its on/off")
    fields = settings_schema.get("fields", {}) if isinstance(settings_schema, Mapping) else {}
    for old, key in raw.items():
        if old == cplug_id or not _NAME.match(old):
            raise ManifestError(f"{where}: {old} is not a retired plugin id")
        if not isinstance(fields.get(key), Mapping) or fields[key].get("kind") != "boolean":
            raise ManifestError(f"{where}: {key} is not a boolean setting in settings_schema.fields")
    return dict(raw)


def _surfaces(cplug_id: str, raw: Any, tool_family: str = "") -> Surfaces:
    where = f"{cplug_id}: surfaces"
    if not isinstance(raw, dict) or set(raw) - SURFACE_KEYS:
        raise ManifestError(f"{where} must be an object of {sorted(SURFACE_KEYS)}")
    for flag in ("routes", "feed", "storage"):
        if not isinstance(raw.get(flag, False), bool):
            raise ManifestError(f"{where}.{flag} must be true or false")
    tools = _names(raw, "mcp_tools", where)
    prefixes = (f"{cplug_id}_",) + ((family_prefix(tool_family),) if tool_family else ())
    for tool in tools:
        for family in TOOL_FAMILIES:
            if family != tool_family and tool.startswith(family_prefix(family)):
                raise ManifestError(f"{where}.mcp_tools: {tool} is a {family} family name, which needs tool_family {family} "
                                    f"granted to {cplug_id} in sdk/tool_families.py")
        if not tool.startswith(prefixes) or tool in prefixes or not re.match(r"^[a-z][a-z0-9_]*$", tool):
            named = " or ".join(f"{p}<verb>" for p in prefixes)
            raise ManifestError(f"{where}.mcp_tools: {tool} must be named {named}")
    for key in ("topics", "widgets"):
        for name in _names(raw, key, where):
            if not _NAME.match(name):
                raise ManifestError(f"{where}.{key}: {name} is not a valid name")
    for key in ("tabs", "menu_links"):
        for name in _names(raw, key, where):
            if name != cplug_id and not name.startswith(f"{cplug_id}-"):
                raise ManifestError(f"{where}.{key}: {name} must be {cplug_id} or start with {cplug_id}-")
    section = raw.get("page_section", "")
    if section and (not isinstance(section, str) or not _NAME.match(section) or not raw.get("tabs")):
        raise ManifestError(f"{where}.page_section must be a lowercase id and needs at least one tab")
    label_key, icon = raw.get("page_section_label_key", ""), raw.get("page_section_icon", "")
    if section:
        if not isinstance(label_key, str) or not label_key.startswith(f"cplug.{cplug_id}."):
            raise ManifestError(f"{where}.page_section_label_key must be a catalog key starting cplug.{cplug_id}.")
        if not isinstance(icon, str) or not _NAME.match(icon):
            raise ManifestError(f"{where}.page_section_icon must be an icon name")
    elif label_key or icon:
        raise ManifestError(f"{where}.page_section_label_key and page_section_icon need page_section")
    return Surfaces(routes=raw.get("routes", False), mcp_tools=tools, topics=_names(raw, "topics", where),
                    tabs=_names(raw, "tabs", where), widgets=_names(raw, "widgets", where),
                    plugins=_names(raw, "plugins", where), menu_links=_names(raw, "menu_links", where),
                    feed=raw.get("feed", False), storage=raw.get("storage", False), page_section=section,
                    page_section_label_key=label_key, page_section_icon=icon)


def _widgets(cplug_id: str, raw: Any, declared: Tuple[str, ...], tier: str) -> Dict[str, Dict[str, Any]]:
    where = f"{cplug_id}: widgets"
    if not isinstance(raw, dict) or not all(isinstance(n, str) and isinstance(b, dict) for n, b in raw.items()):
        raise ManifestError(f"{where} must be an object of widget name to declaration")
    if set(raw) != set(declared):
        raise ManifestError(f"{where} and surfaces.widgets must name the same widgets")
    if raw and tier != "builtin":
        raise ManifestError(f"{where}: widgets are for a builtin plugin only")
    from src.core.item_catalog import ItemCatalogError, parse_widgets  # noqa: PLC0415
    from src.core.item_settings_schema import SettingsSchemaError  # noqa: PLC0415
    from src.core.widget_fits.rules import FitsCatalogError, parse_fits  # noqa: PLC0415

    rows = [{"id": f"{cplug_id}.{name}", **block} for name, block in raw.items()]
    try:
        parse_widgets({"schema": 1, "widgets": rows})
        parse_fits({"widgets": rows})
    except (ItemCatalogError, SettingsSchemaError, FitsCatalogError) as exc:
        raise ManifestError(f"{where}: {exc}") from exc
    return {name: dict(block) for name, block in raw.items()}


def parse_manifest(raw: Any) -> Manifest:
    if not isinstance(raw, dict):
        raise ManifestError("a manifest must be an object")
    cplug_id = raw.get("id")
    if not isinstance(cplug_id, str) or not ID_PATTERN.match(cplug_id):
        raise ManifestError(f"id {cplug_id!r} must match {ID_PATTERN.pattern}")
    if cplug_id in RESERVED_IDS:
        raise ManifestError(f"id {cplug_id} is reserved")
    unknown = set(raw) - _TOP_KEYS
    if unknown:
        raise ManifestError(f"{cplug_id}: unknown field(s) {sorted(unknown)}")
    if raw.get("schema") != 1:
        raise ManifestError(f"{cplug_id}: schema must be 1")
    for key, expect in (("name_key", f"cplug.{cplug_id}.name"), ("description_key", f"cplug.{cplug_id}.description")):
        if raw.get(key) != expect:
            raise ManifestError(f"{cplug_id}: {key} must be {expect}")
    _semver(raw.get("version"), f"{cplug_id}: version")
    _semver(raw.get("min_app_version"), f"{cplug_id}: min_app_version")
    for key in ("icon", "author"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ManifestError(f"{cplug_id}: {key} is required")
    tier = raw.get("tier")
    if tier not in TIERS:
        raise ManifestError(f"{cplug_id}: tier must be one of {TIERS}")
    default_enabled = raw.get("default_enabled")
    if default_enabled is not None and not isinstance(default_enabled, bool) or (default_enabled is True and tier != "builtin"):
        raise ManifestError(f"{cplug_id}: default_enabled is a boolean for a builtin plugin only")
    perms = raw.get("permissions", {})
    if not isinstance(perms, dict) or set(perms) - {"app"}:
        raise ManifestError(f"{cplug_id}: permissions must be an object with app only")
    app = _names(perms, "app", f"{cplug_id}: permissions")
    bad = [p for p in app if not is_declarable(p)]
    if bad:
        raise ManifestError(f"{cplug_id}: unknown app permission(s) {bad}")
    for permission in app:
        if not may_ask(permission, tier):
            raise ManifestError(f"{cplug_id}: the {permission} permission is for a {tier_may_ask_text(permission)} plugin only")
    try:
        ai_features = parse_ai_features(cplug_id, raw.get("ai_features", {}), app)
    except AiFeatureError as exc:
        raise ManifestError(str(exc)) from exc
    try:
        network = parse_network(cplug_id, raw, app)
    except NetworkDeclError as exc:
        raise ManifestError(str(exc)) from exc
    reasons = raw.get("permission_reasons", {})
    if (not isinstance(reasons, dict) or set(reasons) - set(app)
            or not all(isinstance(v, str) and 0 < len(v) <= 200 for v in reasons.values())):
        raise ManifestError(f"{cplug_id}: permission_reasons must map declared permissions to a reason of at most 200 characters")
    tool_family = _tool_family(cplug_id, raw.get("tool_family"))
    surfaces = _surfaces(cplug_id, raw.get("surfaces", {}), tool_family)
    aliases = _tool_aliases(cplug_id, raw.get("mcp_tool_aliases"), surfaces)
    widgets = _widgets(cplug_id, raw.get("widgets", {}), surfaces.widgets, tier)
    settings_schema = raw.get("settings_schema", {"version": 1, "fields": {}})
    from src.core.item_settings_schema import SettingsSchemaError, parse_schema  # noqa: PLC0415

    try:
        parse_schema(settings_schema)
    except SettingsSchemaError as exc:
        raise ManifestError(f"{cplug_id}: settings_schema: {exc}") from exc
    settings_aliases = _settings_aliases(cplug_id, raw.get("settings_aliases"), settings_schema)
    legacy_ids = _legacy_ids(cplug_id, raw.get("legacy_ids"), settings_schema)
    requires = _names(raw, "requires", cplug_id)
    if cplug_id in requires:
        raise ManifestError(f"{cplug_id}: a plugin cannot require itself")
    requires_core = _names(raw, "requires_core", cplug_id)
    unknown_core = [c for c in requires_core if c not in CORE_FEATURES]
    if unknown_core:
        raise ManifestError(f"{cplug_id}: requires_core names unknown core feature(s) {unknown_core}; known: {sorted(CORE_FEATURES)}")
    try:
        owns = parse_ownership(cplug_id, raw.get("owns"))
    except OwnershipError as exc:
        raise ManifestError(str(exc)) from exc
    css_prefix = raw.get("css_prefix", cplug_id)
    if not isinstance(css_prefix, str) or not _CSS.match(css_prefix):
        raise ManifestError(f"{cplug_id}: css_prefix must match {_CSS.pattern}")
    return Manifest(id=cplug_id, name_key=raw["name_key"], description_key=raw["description_key"],
                    version=raw["version"], icon=raw["icon"], author=raw["author"],
                    min_app_version=raw["min_app_version"], tier=tier, default_enabled=default_enabled,
                    permissions=app, surfaces=surfaces, widgets=widgets,
                    settings_schema=settings_schema, css_prefix=css_prefix, requires=requires, requires_core=requires_core,
                    ai_features=ai_features, network=network, permission_reasons=dict(reasons), owns=owns,
                    tool_family=tool_family, mcp_tool_aliases=aliases, settings_aliases=settings_aliases, legacy_ids=legacy_ids)


def load_manifest(module_file: str) -> Manifest:
    path = Path(module_file).with_name("cplug.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"{path}: unreadable manifest ({type(exc).__name__})") from exc
    return with_declared_data(parse_manifest(raw), path.with_name(SIDECAR_FILE))


def with_declared_data(manifest: Manifest, sidecar_path: Path) -> Manifest:
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return manifest
    except (OSError, ValueError) as exc:
        logger.warning("cplug_data_unreadable", cplug=manifest.id, path=str(sidecar_path), error=type(exc).__name__)
        return manifest
    if not isinstance(sidecar, dict) or "data" not in sidecar:
        return manifest
    try:
        return replace(manifest, data=parse_data(sidecar["data"], settings_fields_of(manifest.settings_schema)))
    except DataDeclError as exc:
        logger.warning("cplug_data_invalid", cplug=manifest.id, problems=str(exc))
        return manifest

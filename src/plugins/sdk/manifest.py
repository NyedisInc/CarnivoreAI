
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from src.plugins.sdk.core_features import CORE_FEATURES
from src.plugins.sdk.ai_features import AiFeature, AiFeatureError, parse_ai_features
from src.plugins.sdk.data_decl import DataDecl
from src.plugins.sdk.ownership import Ownership, OwnershipError, parse_ownership
from src.plugins.sdk.network import NetworkDecl, NetworkDeclError, parse_network
from src.plugins.sdk import renamed_from as rf
from src.plugins.sdk._manifest_v2_sections import _EVENT_NAME, _SERVICE_REF
from src.plugins.sdk.permission_registry import (
    EVENTS_PREFIX,
    MANIFEST_TIERS,
    SERVICES_PREFIX,
    is_declarable,
    may_ask,
    tier_may_ask_text,
)
from src.plugins.sdk.tool_families import TOOL_FAMILIES, family_prefix

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
    "mcp_tool_aliases", "settings_aliases", "legacy_ids", rf.FIELD, rf.KEEPS_FIELD,
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
    renamed_from: str = ""
    renamed_from_keeps: Tuple[str, ...] = ()
    data: Optional[Tuple[DataDecl, ...]] = None
    code_digest: str = ""
    views: Tuple[Mapping[str, Any], ...] = ()
    services_consumes: Tuple[str, ...] = ()
    services_provides: Tuple[Mapping[str, Any], ...] = ()
    events_allowed: Tuple[str, ...] = ()
    events_on: Tuple[str, ...] = ()
    events_emit: Tuple[str, ...] = ()
    ui_slots: Tuple[str, ...] = ()
    ui_contribute: Mapping[str, Any] = field(default_factory=dict)
    ui_meta: Mapping[str, Any] = field(default_factory=dict)
    harnesses: Tuple[str, ...] = ()
    channels: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    macros: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    webhooks: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    timers: Mapping[str, int] = field(default_factory=dict)


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


def _tool_aliases(cplug_id: str, raw: Any, surfaces: Surfaces, legacy_ids: Sequence[str] = ()) -> Dict[str, str]:
    where = f"{cplug_id}: mcp_tool_aliases"
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise ManifestError(f"{where} must map an old tool name to a current one")
    for old, current in raw.items():
        owners = (cplug_id, *legacy_ids)
        if not any(old.startswith(f"{o}_") and old != f"{o}_" for o in owners) or not re.match(r"^[a-z][a-z0-9_]*$", old):
            raise ManifestError(f"{where}: {old} must be named {cplug_id}_<verb>" + (f" or {'/'.join(legacy_ids)}_<verb>" if legacy_ids else ""))
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


def _surfaces(cplug_id: str, raw: Any, tool_family: str = "", old_strings: str = "", old_widgets: str = "", old_id: str = "") -> Surfaces:
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
            if not _NAME.match(rf.bare_widget_name(old_widgets, name) if key == "widgets" else name):
                raise ManifestError(f"{where}.{key}: {name} is not a valid name")
    for key in ("tabs", "menu_links"):
        for name in _names(raw, key, where):
            if not rf.tab_allowed(cplug_id, old_id, name):
                raise ManifestError(f"{where}.{key}: {name} must be {cplug_id} or start with {cplug_id}-")
    section = raw.get("page_section", "")
    if section and (not isinstance(section, str) or not _NAME.match(section) or not raw.get("tabs")):
        raise ManifestError(f"{where}.page_section must be a lowercase id and needs at least one tab")
    label_key, icon = raw.get("page_section_label_key", ""), raw.get("page_section_icon", "")
    if section:
        if not isinstance(label_key, str) or not label_key.startswith(rf.string_prefixes(cplug_id, old_strings)):
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


def _widgets(cplug_id: str, raw: Any, declared: Tuple[str, ...], tier: str, old_widgets: str = "") -> Dict[str, Dict[str, Any]]:
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

    rows = [{"id": rf.widget_id(cplug_id, old_widgets, name), **block} for name, block in raw.items()]
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
    try:
        renamed_from = rf.parse_renamed_from(cplug_id, raw.get(rf.FIELD), ID_PATTERN, RESERVED_IDS)
        keeps = rf.parse_keeps(cplug_id, raw.get(rf.KEEPS_FIELD), renamed_from)
    except rf.RenamedFromError as exc:
        raise ManifestError(str(exc)) from exc
    old_strings, old_widgets = rf.kept_old_id(renamed_from, keeps, rf.KEEP_STRINGS), rf.kept_old_id(renamed_from, keeps, rf.KEEP_WIDGETS)
    for key, tail in (("name_key", "name"), ("description_key", "description")):
        if not rf.key_allowed(cplug_id, old_strings, raw.get(key), tail):
            raise ManifestError(f"{cplug_id}: {key} must be cplug.{cplug_id}.{tail}")
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
    services_consumes_list: list[str] = []
    events_allowed_list: list[str] = []
    for permission in app:
        if permission.startswith(SERVICES_PREFIX):
            tail = permission[len(SERVICES_PREFIX):]
            if not _SERVICE_REF.match(tail):
                raise ManifestError(f"{cplug_id}: invalid service permission {permission!r}")
            services_consumes_list.append(tail)
        elif permission.startswith(EVENTS_PREFIX):
            tail = permission[len(EVENTS_PREFIX):]
            if not _EVENT_NAME.match(tail):
                raise ManifestError(f"{cplug_id}: invalid event permission {permission!r}")
            events_allowed_list.append(tail)
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
    surfaces = _surfaces(cplug_id, raw.get("surfaces", {}), tool_family, old_strings, old_widgets, renamed_from)
    legacy_raw = raw.get("legacy_ids")
    aliases = _tool_aliases(cplug_id, raw.get("mcp_tool_aliases"), surfaces, tuple(legacy_raw) if isinstance(legacy_raw, dict) else ())
    widgets = _widgets(cplug_id, raw.get("widgets", {}), surfaces.widgets, tier, old_widgets)
    settings_schema = raw.get("settings_schema", {"version": 1, "fields": {}})
    from src.core.item_settings_schema import SettingsSchemaError, parse_schema  # noqa: PLC0415

    try:
        parse_schema(settings_schema)
    except SettingsSchemaError as exc:
        raise ManifestError(f"{cplug_id}: settings_schema: {exc}") from exc
    settings_aliases = _settings_aliases(cplug_id, raw.get("settings_aliases"), settings_schema)
    legacy_ids = _legacy_ids(cplug_id, raw.get("legacy_ids"), settings_schema)
    requires = _names(raw, "requires", cplug_id)
    if cplug_id in requires or (renamed_from and renamed_from in requires):
        raise ManifestError(f"{cplug_id}: a plugin cannot require itself")
    requires_core = _names(raw, "requires_core", cplug_id)
    unknown_core = [c for c in requires_core if c not in CORE_FEATURES]
    if unknown_core:
        raise ManifestError(f"{cplug_id}: requires_core names unknown core feature(s) {unknown_core}; known: {sorted(CORE_FEATURES)}")
    try:
        owns = parse_ownership(cplug_id, raw.get("owns"), old_strings)
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
                    tool_family=tool_family, mcp_tool_aliases=aliases, settings_aliases=settings_aliases, legacy_ids=legacy_ids,
                    renamed_from=renamed_from, renamed_from_keeps=keeps,
                    services_consumes=tuple(dict.fromkeys(services_consumes_list)),
                    events_allowed=tuple(dict.fromkeys(events_allowed_list)))


def load_manifest(module_file: str) -> Manifest:
    pkg_dir = Path(module_file).parent
    from src.plugins.sdk.manifest_v2 import ManifestV2Error, has_v2_manifest, load_manifest_v2  # noqa: PLC0415

    if not has_v2_manifest(pkg_dir):
        raise ManifestError(f"{pkg_dir}: carnivore.toml or schema = 2 carnivore.json is required")
    try:
        v2 = load_manifest_v2(pkg_dir, tier="builtin", allow_tier_override=True)
    except (ManifestV2Error, FileNotFoundError, OSError, ValueError) as exc:
        raise ManifestError(f"{pkg_dir}: invalid v2 manifest ({exc})") from exc
    surfaces = Surfaces(
        routes=bool(v2.routes) or v2.has_routes,
        mcp_tools=v2.mcp_tools or tuple(str(t["name"]) for t in v2.tools if isinstance(t, Mapping) and "name" in t),
        topics=v2.topics,
        tabs=v2.tabs,
        widgets=v2.ui_widgets,
        plugins=v2.ui_plugins,
        menu_links=v2.menu_links,
        feed=any(e.startswith("feed.") for e in v2.events_on),
        storage=v2.ui_storage if v2.ui_storage is not None else bool(v2.data),
        page_section=v2.page_section,
        page_section_label_key=v2.page_section_label_key,
        page_section_icon=v2.page_section_icon,
    )
    return Manifest(
        id=v2.id,
        name_key=v2.name_key or f"cplug.{v2.id}.name",
        description_key=v2.description_key or f"cplug.{v2.id}.description",
        version=v2.version,
        icon=v2.icon,
        author=v2.author,
        min_app_version=v2.min_app_version or "1.0.0",
        tier=v2.tier,
        default_enabled=v2.default_enabled,
        permissions=v2.permissions,
        surfaces=surfaces,
        settings_schema=v2.settings_schema,
        css_prefix=v2.css_prefix or v2.id,
        widgets=v2.widgets,
        requires=v2.requires,
        requires_core=v2.requires_core,
        ai_features=v2.ai_features,
        network=v2.network,
        permission_reasons=dict(v2.permission_reasons),
        owns=v2.owns,
        tool_family=v2.tool_family,
        mcp_tool_aliases=v2.mcp_tool_aliases,
        settings_aliases=v2.settings_aliases,
        legacy_ids=v2.legacy_ids,
        renamed_from=v2.renamed_from,
        renamed_from_keeps=v2.renamed_from_keeps,
        data=v2.data,
        views=v2.views,
        services_consumes=v2.services_consumes,
        services_provides=v2.services_provides,
        events_allowed=v2.events_allowed,
        events_on=v2.events_on,
        events_emit=v2.events_emit,
        ui_slots=v2.ui_slots,
        ui_contribute=v2.ui_contribute,
        ui_meta=v2.ui_meta,
        harnesses=v2.harnesses,
        channels=v2.channels,
        macros=v2.macros,
        webhooks=v2.webhooks,
        timers=v2.timers,
    )

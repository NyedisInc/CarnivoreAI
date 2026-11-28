
from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

if __package__:
    from ._manifest_v2_sections import (
        DEFAULT_VIEW_FITS as DEFAULT_VIEW_FITS,
        MACRO_ACTIONS as MACRO_ACTIONS,
        MAX_CHANNELS as MAX_CHANNELS,
        MAX_EVENTS as MAX_EVENTS,
        MAX_FIT_H as MAX_FIT_H,
        MAX_FIT_W as MAX_FIT_W,
        MAX_HARNESSES as MAX_HARNESSES,
        MAX_MACRO_STEPS as MAX_MACRO_STEPS,
        MAX_MACROS as MAX_MACROS,
        MAX_ROUTES as MAX_ROUTES,
        MAX_TIMERS as MAX_TIMERS,
        MAX_TOOLS as MAX_TOOLS,
        MAX_VIEW_FILES as MAX_VIEW_FILES,
        MAX_VIEWS as MAX_VIEWS,
        MAX_WEBHOOKS as MAX_WEBHOOKS,
        MIN_TIMER_SECONDS as MIN_TIMER_SECONDS,
        MAX_TIMER_SECONDS as MAX_TIMER_SECONDS,
        RESERVED_ROUTES as RESERVED_ROUTES,
        TOOL_DESCRIPTION_MAX as TOOL_DESCRIPTION_MAX,
        TOOL_GATES as TOOL_GATES,
        TRUST_UNRESTRICTED as TRUST_UNRESTRICTED,
        VIEW_SURFACES as VIEW_SURFACES,
        VIEW_TYPES as VIEW_TYPES,
        ManifestV2Error as ManifestV2Error,
        _EVENT_NAME,
        _HEADER_NAME,
        _SECRET_NAME,
        _SERVICE_REF,
        _check_rel_path,
        _json_clone,
        _parse_channels,
        _parse_events,
        _parse_harnesses,
        _parse_macros,
        _parse_services,
        _parse_timers,
        _parse_tools,
        _parse_ui,
        _parse_webhooks,
        _validate_settings_schema,
        clean_text as clean_text,
    )
    from . import api_contract, renamed_from as rf
    from .ai_features import AiFeature, AiFeatureError, parse_ai_features
    from .core_features import CORE_FEATURES
    from .data_decl import DataDecl, DataDeclError, parse_data
    from .network import (
        FORBIDDEN_HEADERS, FORBIDDEN_HEADER_PREFIXES, PERMISSION_PREFIXES, WRITE_METHODS,
        Auth, LanHost, NetworkDecl, NetworkDeclError, NetworkHost, Secret,
        _lan_host, _methods, _paths, normalize_host, literal_kind,
    )
    from .ownership import Ownership, OwnershipError, parse_ownership
    from .permission_registry import ALL_TIERS, EVENTS_PREFIX, FIRST_PARTY_TIERS, SERVICES_PREFIX, TIER_CATALOG, is_declarable, may_ask
    from .tool_families import TOOL_FAMILIES
else:
    from _manifest_v2_sections import (  # type: ignore[no-redef]
        DEFAULT_VIEW_FITS, MACRO_ACTIONS, MAX_CHANNELS, MAX_EVENTS, MAX_FIT_H, MAX_FIT_W, MAX_HARNESSES,  # noqa: F401
        MAX_MACRO_STEPS, MAX_MACROS, MAX_ROUTES, MAX_TIMERS, MAX_TOOLS, MAX_VIEW_FILES, MAX_VIEWS,  # noqa: F401
        MAX_WEBHOOKS, MIN_TIMER_SECONDS, MAX_TIMER_SECONDS, RESERVED_ROUTES, TOOL_DESCRIPTION_MAX,  # noqa: F401
        TOOL_GATES, TRUST_UNRESTRICTED, VIEW_SURFACES, VIEW_TYPES, ManifestV2Error,  # noqa: F401
        _EVENT_NAME, _HEADER_NAME, _SECRET_NAME, _SERVICE_REF, _check_rel_path, _json_clone,
        _parse_channels, _parse_events, _parse_harnesses, _parse_macros, _parse_services,
        _parse_timers, _parse_tools, _parse_ui, _parse_webhooks, _validate_settings_schema, clean_text,
    )
    import api_contract  # type: ignore[no-redef]
    import renamed_from as rf  # type: ignore[no-redef]
    from ai_features import AiFeature, AiFeatureError, parse_ai_features  # type: ignore[no-redef]
    from core_features import CORE_FEATURES  # type: ignore[no-redef]
    from data_decl import DataDecl, DataDeclError, parse_data  # type: ignore[no-redef]
    from network import (  # type: ignore[no-redef]
        FORBIDDEN_HEADERS, FORBIDDEN_HEADER_PREFIXES, PERMISSION_PREFIXES, WRITE_METHODS,
        Auth, LanHost, NetworkDecl, NetworkDeclError, NetworkHost, Secret,
        _lan_host, _methods, _paths, normalize_host, literal_kind,
    )
    from ownership import Ownership, OwnershipError, parse_ownership  # type: ignore[no-redef]
    from permission_registry import ALL_TIERS, EVENTS_PREFIX, FIRST_PARTY_TIERS, SERVICES_PREFIX, TIER_CATALOG, is_declarable, may_ask  # type: ignore[no-redef]
    from tool_families import TOOL_FAMILIES  # type: ignore[no-redef]

_FEED_EVENT_FAMILIES = frozenset({"feed.meta", "feed.scrubbed", "feed.raw", "mcp.health"})

TOML_FILE = "carnivore.toml"
JSON_FILE = "carnivore.json"
TIER_LOCAL = "local"
V2_TIERS = (*ALL_TIERS, TIER_LOCAL)

KINDS = ("plugin", "skill", "agent-plugin", "mod", "theme", "widget", "loadout")
RUN_MODES = ("rpc", "oneshot")

ID_PATTERN = re.compile(r"^[a-z][a-z0-9]{1,23}$")
RESERVED_IDS = frozenset({
    "core", "cplug", "cplugs", "plugin", "plugins", "app", "session", "sessions", "projects",
    "pipeline", "log", "board", "ai", "approval", "auto", "usage", "alerts", "conversation",
    "transcript", "perf", "self", "whoami",
})
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_DNS_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_CSS = re.compile(r"^[a-z][a-z0-9-]{1,23}$")
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_ALIAS_TOOL = re.compile(r"^[a-z][a-z0-9_]*$")
_PREVIEW_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*\.(png|jpg|jpeg|webp)$", re.IGNORECASE)

NAME_MAX = 60
DESCRIPTION_MAX = 400

_FIRST_PARTY_TOP_KEYS = frozenset({
    "name_key", "description_key", "css_prefix", "tool_family", "mcp_tool_aliases",
    "settings_aliases", "legacy_ids", rf.FIELD, rf.KEEPS_FIELD, "widgets",
})
_TOP_KEYS = frozenset({
    "schema", "id", "name", "version", "kind", "description", "author", "license", "min_app_version",
    "icon", "default_enabled", "tier", "run", "permissions", "ui", "mcp", "events", "services",
    "timers", "webhooks", "channels", "macros", "harnesses", "settings_schema", "data", "owns",
    "requires", "requires_core", "ai_features", "trust", "preview", "screenshots", "icon_file", "api_version",
}) | _FIRST_PARTY_TOP_KEYS
_PERM_KEYS = frozenset({"read", "write", "network", "lan", "secrets", "services", "events", "reasons", "app"})
_RUN_KEYS = frozenset({"cmd", "mode"})
_SECRET_KEYS = frozenset({"key", "name", "label", "help", "required"})
_SAFE_ABS_RUN_DIRS = frozenset({"/bin", "/usr/bin", "/opt/homebrew/bin", "/usr/local/bin"})
_SAFE_ABS_RUN_NAMES = frozenset({"bash", "sh", "python", "python3", "node", "bun", "uv"})

_READ_MAP: Dict[str, str] = {
    "sessions": "sessions.read",
    "sessions.read": "sessions.read",
    "projects": "sessions.read",
    "output": "sessions.output",
    "sessions.output": "sessions.output",
    "git": "projects.git.read",
    "projects.git": "projects.git.read",
    "projects.git.read": "projects.git.read",
    "ledger": "ledger.read",
    "ledger.read": "ledger.read",
    "mcp.health": "mcp.health.read",
    "mcp.health.read": "mcp.health.read",
    "flow": "flow.read",
    "flow.read": "flow.read",
    "activity": "activity.read",
    "activity.read": "activity.read",
    "feed.meta": "feed.view: meta",
    "feed:meta": "feed.view: meta",
    "feed.view: meta": "feed.view: meta",
    "feed.scrubbed": "feed.view: scrubbed",
    "feed:scrub": "feed.view: scrubbed",
    "feed.view: scrubbed": "feed.view: scrubbed",
    "feed.raw": "feed.view: raw",
    "feed:raw": "feed.view: raw",
    "feed.view: raw": "feed.view: raw",
}

_WRITE_MAP: Dict[str, str] = {
    "notify": "notify",
    "exports": "exports.write",
    "exports.write": "exports.write",
    "sessions.message": "sessions.message",
    "sessions.create": "sessions.create",
    "sessions.control": "sessions.control",
    "git.snapshot": "projects.git.snapshot",
    "projects.git.snapshot": "projects.git.snapshot",
    "agent_writes": "agent_writes",
    "imports": "imports.write",
    "imports.write": "imports.write",
    "swarm": "swarm",
    "work": "work",
}


@dataclass(frozen=True)
class ManifestV2:

    schema: int
    id: str
    name: str
    version: str
    kind: str
    description: str
    author: str
    license: str = ""
    min_app_version: str = ""
    icon: str = "plug"
    tier: str = TIER_CATALOG
    default_enabled: Optional[bool] = None
    tier0: bool = True
    run_cmd: Tuple[str, ...] = ()
    run_mode: str = "rpc"
    entry: str = ""
    permissions: Tuple[str, ...] = ()
    permission_reasons: Mapping[str, str] = field(default_factory=dict)
    network: NetworkDecl = field(default_factory=NetworkDecl)
    services_consumes: Tuple[str, ...] = ()
    services_provides: Tuple[Mapping[str, Any], ...] = ()
    events_allowed: Tuple[str, ...] = ()
    events_on: Tuple[str, ...] = ()
    events_emit: Tuple[str, ...] = ()
    tools: Tuple[Mapping[str, Any], ...] = ()
    routes: Tuple[str, ...] = ()
    views: Tuple[Mapping[str, Any], ...] = ()
    page: Optional[Mapping[str, Any]] = None
    topics: Tuple[str, ...] = ()
    ui_meta: Mapping[str, Any] = field(default_factory=dict)
    ui_contribute: Mapping[str, Any] = field(default_factory=dict)
    ui_slots: Tuple[str, ...] = ()
    timers: Mapping[str, int] = field(default_factory=dict)
    webhooks: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    channels: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    macros: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    harnesses: Tuple[str, ...] = ()
    settings_schema: Mapping[str, Any] = field(default_factory=lambda: {"version": 1, "fields": {}})
    data: Optional[Tuple[DataDecl, ...]] = None
    owns: Ownership = field(default_factory=Ownership)
    requires: Tuple[str, ...] = ()
    requires_core: Tuple[str, ...] = ()
    ai_features: Mapping[str, AiFeature] = field(default_factory=dict)
    trust: str = ""
    preview: str = ""
    screenshots: Tuple[str, ...] = ()
    icon_file: str = ""
    api_version: int = 1
    name_key: str = ""
    description_key: str = ""
    css_prefix: str = ""
    tool_family: str = ""
    mcp_tool_aliases: Mapping[str, str] = field(default_factory=dict)
    settings_aliases: Mapping[str, str] = field(default_factory=dict)
    legacy_ids: Mapping[str, str] = field(default_factory=dict)
    renamed_from: str = ""
    renamed_from_keeps: Tuple[str, ...] = ()
    widgets: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    has_routes: bool = False
    ui_storage: Optional[bool] = None
    mcp_tools: Tuple[str, ...] = ()
    tabs: Tuple[str, ...] = ()
    menu_links: Tuple[str, ...] = ()
    ui_plugins: Tuple[str, ...] = ()
    ui_widgets: Tuple[str, ...] = ()
    page_section: str = ""
    page_section_label_key: str = ""
    page_section_icon: str = ""


MAX_MANIFEST_BYTES = 1024 * 1024


def has_v2_manifest(code_root: Path) -> bool:
    root = Path(code_root)
    if (root / TOML_FILE).is_file():
        return True
    json_path = root / JSON_FILE
    if not json_path.is_file():
        return False
    try:
        if json_path.stat().st_size > MAX_MANIFEST_BYTES:
            return True
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(raw, dict) and type(raw.get("schema")) is int and raw.get("schema") == 2


def load_raw_v2(code_root: Path) -> Tuple[Dict[str, Any], str]:
    root = Path(code_root)
    toml_path = root / TOML_FILE
    json_path = root / JSON_FILE
    has_toml = toml_path.is_file()
    has_json = json_path.is_file()
    has_cplug = (root / "cplug.json").is_file()
    if has_toml and has_json:
        raise ManifestV2Error(f"both {TOML_FILE} and {JSON_FILE} exist; keep one")
    if has_toml:
        if has_cplug:
            raise ManifestV2Error(f"{TOML_FILE} cannot coexist with cplug.json")
        try:
            if toml_path.stat().st_size > MAX_MANIFEST_BYTES:
                raise ManifestV2Error(f"{TOML_FILE}: exceeds {MAX_MANIFEST_BYTES} bytes")
            raw = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ManifestV2Error(f"{TOML_FILE}: unreadable or invalid TOML ({type(exc).__name__})") from exc
        if not isinstance(raw, dict):
            raise ManifestV2Error(f"{TOML_FILE}: root must be a table")
        return raw, TOML_FILE
    if has_json:
        if has_cplug:
            raise ManifestV2Error(f"v2 {JSON_FILE} cannot coexist with cplug.json")
        try:
            if json_path.stat().st_size > MAX_MANIFEST_BYTES:
                raise ManifestV2Error(f"{JSON_FILE}: exceeds {MAX_MANIFEST_BYTES} bytes")
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ManifestV2Error(f"{JSON_FILE}: unreadable or invalid JSON ({type(exc).__name__})") from exc
        if not isinstance(raw, dict):
            raise ManifestV2Error(f"{JSON_FILE}: root must be an object")
        return raw, JSON_FILE
    raise FileNotFoundError(f"{code_root}: neither {TOML_FILE} nor {JSON_FILE} exists")


def _req_text(raw: Mapping[str, Any], key: str, limit: int, where: str) -> str:
    text = clean_text(raw.get(key), limit)
    if not text:
        raise ManifestV2Error(f"{where}: {key} must be a non-empty string")
    return text


def _parse_run(raw: Any, where: str) -> Tuple[bool, Tuple[str, ...], str, str]:
    if raw is None:
        return True, (), "rpc", ""
    if not isinstance(raw, dict) or set(raw) - _RUN_KEYS:
        raise ManifestV2Error(f"{where}: [run] may contain only {sorted(_RUN_KEYS)}")
    cmd = raw.get("cmd")
    if not isinstance(cmd, list) or not cmd or len(cmd) > 16 or not all(isinstance(a, str) and a.strip() and "\x00" not in a for a in cmd):
        raise ManifestV2Error(f"{where}: [run].cmd must be a non-empty list of strings")
    mode = raw.get("mode", "rpc")
    if mode not in RUN_MODES:
        raise ManifestV2Error(f"{where}: [run].mode must be one of {RUN_MODES}")
    cmd0 = cmd[0]
    if ".." in Path(cmd0).parts or "\\" in cmd0:
        raise ManifestV2Error(f"{where}: [run].cmd[0] must not contain path traversal")
    exe = Path(cmd0).name.lower()
    if cmd0.startswith("/"):
        if str(Path(cmd0).parent) not in _SAFE_ABS_RUN_DIRS or exe not in _SAFE_ABS_RUN_NAMES:
            raise ManifestV2Error(f"{where}: [run].cmd[0] absolute path {cmd0!r} is not an allowed runtime")
    entry = ""
    if exe.startswith("python"):
        for arg in cmd[1:]:
            if arg.startswith("-"):
                continue
            _check_rel_path(arg, f"{where}: [run].cmd")
            if arg.endswith(".py"):
                entry = arg
            break
    elif exe == "uv":
        skip_next = False
        seen_sub = False
        for arg in cmd[1:]:
            if skip_next:
                skip_next = False
                continue
            if arg in ("-p", "--python", "--with", "--directory", "--project"):
                skip_next = True
                continue
            if arg.startswith("-"):
                continue
            if not seen_sub and arg == "run":
                seen_sub = True
                continue
            _check_rel_path(arg, f"{where}: [run].cmd")
            if arg.endswith(".py"):
                entry = arg
            break
    elif exe in ("node", "bun", "bash", "sh"):
        first = True
        for arg in cmd[1:]:
            if arg.startswith("-"):
                continue
            if first and exe == "bun" and arg == "run":
                first = False
                continue
            first = False
            _check_rel_path(arg, f"{where}: [run].cmd")
            entry = arg
            break
        if not entry:
            entry = cmd0
    else:
        if cmd0.startswith("/"):
            raise ManifestV2Error(f"{where}: [run].cmd binary must stay inside plugin directory")
        for arg in cmd[1:]:
            if ".." in Path(arg).parts:
                raise ManifestV2Error(f"{where}: [run].cmd must not contain '..' path traversal")
        entry = cmd0
    return False, tuple(cmd), mode, entry


def _parse_secrets(cplug_id: str, raw_secrets: Any, webhooks: Mapping[str, Mapping[str, str]], where: str) -> Tuple[Secret, ...]:
    if raw_secrets is None:
        raw_secrets = []
    if not isinstance(raw_secrets, list):
        raise ManifestV2Error(f"{where}: [permissions].secrets must be a list")
    out: List[Secret] = []
    seen = set()
    for i, item in enumerate(raw_secrets):
        if isinstance(item, str):
            name = item
            if not _SECRET_NAME.match(name) or name in seen:
                raise ManifestV2Error(f"{where}: secrets[{i}] key must be unique and match {_SECRET_NAME.pattern}")
            seen.add(name)
            out.append(Secret(name=name, label=name, help=name))
            continue
        if not isinstance(item, dict) or set(item) - _SECRET_KEYS:
            raise ManifestV2Error(f"{where}: secrets[{i}] has invalid keys")
        name = item.get("key") if "key" in item else item.get("name")
        if not isinstance(name, str) or not _SECRET_NAME.match(name) or name in seen:
            raise ManifestV2Error(f"{where}: secrets[{i}] key must be unique and match {_SECRET_NAME.pattern}")
        label = clean_text(item.get("label", ""), 120)
        if not label:
            raise ManifestV2Error(f"{where}: secrets[{i}] label is required")
        help_text = clean_text(item.get("help", label), 200) or label
        if "required" in item and not isinstance(item["required"], bool):
            raise ManifestV2Error(f"{where}: secrets[{i}].required must be a bool")
        seen.add(name)
        out.append(Secret(name=name, label=label, help=help_text))
    for hook_name, cfg in webhooks.items():
        s_name = cfg["hmac_secret"]
        if s_name not in seen:
            seen.add(s_name)
            out.append(Secret(name=s_name, label=f"{hook_name} webhook secret", help=f"HMAC secret for inbound webhook {hook_name}"))
    return tuple(out)


def _parse_network_host(cplug_id: str, i: int, item: Any, secrets_by_name: Mapping[str, Secret], where: str) -> NetworkHost:
    if isinstance(item, str):
        block: Dict[str, Any] = {"host": item, "reason": f"Connect to {item}"}
    elif isinstance(item, dict):
        block = dict(item)
        if "reason" not in block and isinstance(block.get("host"), str):
            block["reason"] = f"Connect to {block['host']}"
    else:
        raise ManifestV2Error(f"{where}: network[{i}] must be a hostname or object")
    unknown = set(block) - {"host", "reason", "methods", "paths", "auth"}
    if unknown or not isinstance(block.get("host"), str):
        raise ManifestV2Error(f"{where}: network[{i}] invalid host declaration")
    try:
        host = normalize_host(block["host"])
    except ValueError as exc:
        raise ManifestV2Error(f"{where}: network[{i}].host is not valid") from exc
    labels = host.split(".")
    if literal_kind(host) or len(labels) < 2 or not all(_DNS_LABEL.match(x) for x in labels) or host.endswith(".local"):
        raise ManifestV2Error(f"{where}: network[{i}].host must be a public DNS name")
    reason = clean_text(block.get("reason", ""), 300) or f"Connect to {host}"
    try:
        methods = _methods(f"{where}.network[{i}]", block.get("methods"))
        paths = _paths(f"{where}.network[{i}]", block.get("paths"))
    except NetworkDeclError as exc:
        raise ManifestV2Error(str(exc)) from exc
    auth = None
    if block.get("auth") is not None:
        raw_auth = block["auth"]
        if (
            not isinstance(raw_auth, dict)
            or set(raw_auth) != {"secret", "header", "scheme"}
            or not isinstance(raw_auth["secret"], str)
            or raw_auth["secret"] not in secrets_by_name
            or not isinstance(raw_auth["header"], str)
            or not _HEADER_NAME.match(raw_auth["header"])
            or raw_auth["header"].lower() in FORBIDDEN_HEADERS
            or raw_auth["header"].lower().startswith(FORBIDDEN_HEADER_PREFIXES)
            or not isinstance(raw_auth["scheme"], str)
            or not re.match(r"^[A-Za-z0-9-]{0,32}$", raw_auth["scheme"])
        ):
            raise ManifestV2Error(f"{where}: network[{i}].auth is invalid")
        auth = Auth(raw_auth["secret"], raw_auth["header"], raw_auth["scheme"])
    return NetworkHost(host=host, reason=reason, methods=methods, paths=paths, auth=auth)


def _parse_permissions(
    cplug_id: str,
    raw_perms: Any,
    webhooks: Mapping[str, Mapping[str, str]],
    tier: str,
    where: str,
    *,
    extra_services: Tuple[str, ...] = (),
    extra_events: Tuple[str, ...] = (),
) -> Tuple[Tuple[str, ...], NetworkDecl, Mapping[str, str], Tuple[str, ...], Tuple[str, ...]]:
    if raw_perms is None:
        raw_perms = {}
    if not isinstance(raw_perms, dict) or set(raw_perms) - _PERM_KEYS:
        raise ManifestV2Error(f"{where}: [permissions] may contain only {sorted(_PERM_KEYS)}")

    secrets = _parse_secrets(cplug_id, raw_perms.get("secrets"), webhooks, where)
    secrets_by_name = {s.name: s for s in secrets}

    net_raw = raw_perms.get("network", [])
    if not isinstance(net_raw, list):
        raise ManifestV2Error(f"{where}: [permissions].network must be a list")
    hosts = tuple(_parse_network_host(cplug_id, i, item, secrets_by_name, where) for i, item in enumerate(net_raw))
    if len({h.host for h in hosts}) != len(hosts):
        raise ManifestV2Error(f"{where}: duplicate host in [permissions].network")

    lan_raw = raw_perms.get("lan", [])
    if not isinstance(lan_raw, list):
        raise ManifestV2Error(f"{where}: [permissions].lan must be a list")
    lans: List[LanHost] = []
    for i, item in enumerate(lan_raw):
        block = {"host": item, "reason": f"Connect to {item}"} if isinstance(item, str) else item
        try:
            lans.append(_lan_host(cplug_id, i, block))
        except NetworkDeclError as exc:
            raise ManifestV2Error(str(exc)) from exc
    if len({h.entry for h in lans}) != len(lans):
        raise ManifestV2Error(f"{where}: duplicate entry in [permissions].lan")

    perms: List[str] = []
    seen = set()

    def add_perm(p: str) -> None:
        if p not in seen:
            seen.add(p)
            perms.append(p)

    for key, mapping in (("read", _READ_MAP), ("write", _WRITE_MAP)):
        vals = raw_perms.get(key, [])
        if not isinstance(vals, list) or not all(isinstance(v, str) and v for v in vals):
            raise ManifestV2Error(f"{where}: [permissions].{key} must be a list of strings")
        for v in vals:
            mapped = mapping.get(v)
            if mapped is None:
                raise ManifestV2Error(f"{where}: unknown [permissions].{key} entry {v!r}")
            add_perm(mapped)

    for h in hosts:
        add_perm(h.permission)
        if any(m in WRITE_METHODS for m in h.methods):
            add_perm(h.write_permission)
    for lh in lans:
        add_perm(lh.permission)
        if any(m in WRITE_METHODS for m in lh.methods):
            add_perm(lh.write_permission)

    app_extra = raw_perms.get("app", [])
    if not isinstance(app_extra, list) or not all(isinstance(v, str) and v for v in app_extra):
        raise ManifestV2Error(f"{where}: [permissions].app must be a list of strings")
    perm_services_from_app: List[str] = []
    perm_events_from_app: List[str] = []
    for p in app_extra:
        if p.startswith(PERMISSION_PREFIXES):
            raise ManifestV2Error(f"{where}: network/lan permissions must be declared under network/lan")
        if p.startswith(SERVICES_PREFIX):
            tail = p[len(SERVICES_PREFIX):]
            if not _SERVICE_REF.match(tail):
                raise ManifestV2Error(f"{where}: invalid service permission {p!r}")
            perm_services_from_app.append(tail)
        elif p.startswith(EVENTS_PREFIX):
            tail = p[len(EVENTS_PREFIX):]
            if not _EVENT_NAME.match(tail):
                raise ManifestV2Error(f"{where}: invalid event permission {p!r}")
            perm_events_from_app.append(tail)
        add_perm(p)

    for hook_name in webhooks:
        add_perm(f"hooks.inbound:{hook_name}")

    services_raw = raw_perms.get("services", [])
    if not isinstance(services_raw, list) or not all(isinstance(s, str) and _SERVICE_REF.match(s) for s in services_raw):
        raise ManifestV2Error(f"{where}: [permissions].services must be valid service refs")
    events_raw = raw_perms.get("events", [])
    if not isinstance(events_raw, list) or not all(isinstance(e, str) and _EVENT_NAME.match(e) for e in events_raw):
        raise ManifestV2Error(f"{where}: [permissions].events must be valid event names")

    merged_services = tuple(dict.fromkeys([*services_raw, *perm_services_from_app, *extra_services]))
    merged_events = tuple(dict.fromkeys([*events_raw, *perm_events_from_app, *extra_events]))
    for svc in merged_services:
        add_perm(f"{SERVICES_PREFIX}{svc}")
    for ev in merged_events:
        add_perm(f"{EVENTS_PREFIX}{ev}")

    for p in perms:
        if not is_declarable(p):
            raise ManifestV2Error(f"{where}: unknown or non-declarable permission {p!r}")
        if not may_ask(p, tier):
            raise ManifestV2Error(f"{where}: tier {tier!r} may not request permission {p!r}")

    reasons_raw = raw_perms.get("reasons", {})
    if not isinstance(reasons_raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in reasons_raw.items()):
        raise ManifestV2Error(f"{where}: [permissions].reasons must map permission strings to descriptions")
    reasons = {k: clean_text(v, 300) for k, v in reasons_raw.items() if clean_text(v, 300)}

    return tuple(perms), NetworkDecl(hosts, tuple(lans), secrets), reasons, merged_services, merged_events


def _parse_tool_family(cplug_id: str, raw: Any) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str) or raw not in TOOL_FAMILIES:
        raise ManifestV2Error(f"{cplug_id}: tool_family must be one of {sorted(TOOL_FAMILIES)}")
    if cplug_id not in TOOL_FAMILIES[raw]:
        raise ManifestV2Error(f"{cplug_id}: tool_family {raw} is not granted to {cplug_id} (sdk/tool_families.py)")
    return raw


def _parse_tool_aliases(
    cplug_id: str,
    raw: Any,
    mcp_tools: Tuple[str, ...],
    legacy_ids: Tuple[str, ...] = (),
) -> Dict[str, str]:
    where = f"{cplug_id}: mcp_tool_aliases"
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise ManifestV2Error(f"{where} must map an old tool name to a current one")
    owners = (cplug_id, *legacy_ids)
    for old, current in raw.items():
        if not any(old.startswith(f"{o}_") and old != f"{o}_" for o in owners) or not _ALIAS_TOOL.match(old):
            raise ManifestV2Error(f"{where}: {old} must be named {cplug_id}_<verb>")
        if current not in mcp_tools:
            raise ManifestV2Error(f"{where}: {old} points at {current}, which is not in [mcp].tools")
        if old in mcp_tools:
            raise ManifestV2Error(f"{where}: {old} is also a current tool name in [mcp].tools")
    if len(set(raw.values())) != len(raw):
        raise ManifestV2Error(f"{where}: two old names point at one current name")
    return dict(raw)


def _parse_settings_aliases(cplug_id: str, raw: Any, settings_schema: Mapping[str, Any]) -> Dict[str, str]:
    where = f"{cplug_id}: settings_aliases"
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise ManifestV2Error(f"{where} must map a current setting key to the retired key it replaced")
    fields = settings_schema.get("fields", {}) if isinstance(settings_schema, Mapping) else {}
    for current, retired in raw.items():
        if current not in fields:
            raise ManifestV2Error(f"{where}: {current} is not in settings_schema.fields")
        if retired in fields:
            raise ManifestV2Error(f"{where}: {retired} is also a current setting key")
    if len(set(raw.values())) != len(raw):
        raise ManifestV2Error(f"{where}: two current keys name one retired key")
    return dict(raw)


def _parse_legacy_ids(cplug_id: str, raw: Any, settings_schema: Mapping[str, Any]) -> Dict[str, str]:
    where = f"{cplug_id}: legacy_ids"
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise ManifestV2Error(f"{where} must map a retired plugin id to the setting that carries its on/off")
    fields = settings_schema.get("fields", {}) if isinstance(settings_schema, Mapping) else {}
    for old, key in raw.items():
        if old == cplug_id or not _NAME.match(old):
            raise ManifestV2Error(f"{where}: {old} is not a retired plugin id")
        if not isinstance(fields.get(key), Mapping) or fields[key].get("kind") != "boolean":
            raise ManifestV2Error(f"{where}: {key} is not a boolean setting in settings_schema.fields")
    return dict(raw)


def _parse_widgets(
    cplug_id: str,
    raw: Any,
    declared: Tuple[str, ...],
    tier: str,
    old_widgets: str = "",
) -> Dict[str, Dict[str, Any]]:
    where = f"{cplug_id}: widgets"
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or not all(isinstance(n, str) and isinstance(b, dict) for n, b in raw.items()):
        raise ManifestV2Error(f"{where} must be an object of widget name to declaration")
    if set(raw) != set(declared):
        raise ManifestV2Error(f"{where} and [ui].widgets must name the same widgets")
    if not raw:
        return {}
    if tier != "builtin":
        raise ManifestV2Error(f"{where}: widgets are for a builtin plugin only")
    from src.core.item_catalog import ItemCatalogError, parse_widgets  # noqa: PLC0415
    from src.core.item_settings_schema import SettingsSchemaError  # noqa: PLC0415
    from src.core.widget_fits.rules import FitsCatalogError, parse_fits  # noqa: PLC0415

    clean = _json_clone(raw, where)
    rows = [{"id": rf.widget_id(cplug_id, old_widgets, name), **block} for name, block in clean.items()]
    try:
        parse_widgets({"schema": 1, "widgets": rows})
        parse_fits({"widgets": rows})
    except (ItemCatalogError, SettingsSchemaError, FitsCatalogError) as exc:
        raise ManifestV2Error(f"{where}: {exc}") from exc
    return {name: dict(block) for name, block in clean.items()}


def parse_manifest_v2(
    raw: Any,
    *,
    expected_id: Optional[str] = None,
    tier: str = TIER_CATALOG,
    expected_tier: Optional[str] = None,
    allow_tier_override: bool = False,
) -> ManifestV2:
    if not isinstance(raw, dict):
        raise ManifestV2Error("manifest must be an object/table")
    schema = raw.get("schema")
    if type(schema) is not int or schema != 2:
        raise ManifestV2Error("schema must be integer 2")
    cplug_id = raw.get("id")
    if not isinstance(cplug_id, str) or not ID_PATTERN.match(cplug_id):
        raise ManifestV2Error(f"id {cplug_id!r} must match {ID_PATTERN.pattern}")
    if cplug_id in RESERVED_IDS:
        raise ManifestV2Error(f"id {cplug_id!r} is reserved")
    if expected_id is not None and cplug_id != expected_id:
        raise ManifestV2Error(f"id {cplug_id!r} does not match expected {expected_id!r}")
    where = f"manifest {cplug_id}"
    unknown = sorted(set(raw) - _TOP_KEYS)
    if unknown:
        raise ManifestV2Error(f"{where}: unknown field(s) {unknown}")

    target_tier = expected_tier if expected_tier is not None else tier
    eff_tier = raw.get("tier", target_tier)
    if not isinstance(eff_tier, str) or eff_tier not in V2_TIERS:
        raise ManifestV2Error(f"{where}: tier must be one of {V2_TIERS}")
    if expected_tier is not None and eff_tier != expected_tier:
        raise ManifestV2Error(f"{where}: tier must be {expected_tier!r}")
    if not allow_tier_override and "tier" in raw and eff_tier != target_tier:
        raise ManifestV2Error(f"{where}: tier override {eff_tier!r} is not permitted")

    is_first_party = eff_tier in FIRST_PARTY_TIERS
    if not is_first_party:
        bad_fp = sorted(set(raw) & _FIRST_PARTY_TOP_KEYS)
        if bad_fp:
            raise ManifestV2Error(f"{where}: field(s) {bad_fp} are only allowed for first-party tiers")

    api_version = raw.get("api_version", 1)
    if not api_contract.is_served(api_version):
        raise ManifestV2Error(f"{where}: api_version {api_version!r} is not served")

    name = _req_text(raw, "name", NAME_MAX, where)
    description = _req_text(raw, "description", DESCRIPTION_MAX, where)
    author = _req_text(raw, "author", 80, where)
    version = raw.get("version")
    if not isinstance(version, str) or not _SEMVER.match(version):
        raise ManifestV2Error(f"{where}: version must be major.minor.patch")
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ManifestV2Error(f"{where}: kind must be one of {KINDS}")
    license_str = clean_text(raw.get("license", ""), 40)
    if "min_app_version" in raw:
        min_app = raw["min_app_version"]
        if not isinstance(min_app, str) or not _SEMVER.match(min_app):
            raise ManifestV2Error(f"{where}: min_app_version must be major.minor.patch")
    else:
        min_app = ""
    icon = clean_text(raw.get("icon", ""), 40) or "plug"

    default_enabled = raw.get("default_enabled")
    if default_enabled is not None and type(default_enabled) is not bool:
        raise ManifestV2Error(f"{where}: default_enabled must be boolean")
    if eff_tier == TIER_CATALOG and default_enabled is True:
        raise ManifestV2Error(f"{where}: catalog tier plugins cannot set default_enabled = true")

    trust = raw.get("trust", "")
    if "trust" in raw and trust != "unrestricted":
        raise ManifestV2Error(f'{where}: trust, when present, must be "unrestricted"')
    preview = ""
    if "preview" in raw:
        p = raw["preview"]
        if not isinstance(p, str) or not _PREVIEW_PATH.match(p) or ".." in Path(p).parts:
            raise ManifestV2Error(f"{where}: preview must be a relative image path")
        preview = p
    screenshots: Tuple[str, ...] = ()
    if "screenshots" in raw:
        raw_shots = raw["screenshots"]
        if not isinstance(raw_shots, list) or len(raw_shots) > 4:
            raise ManifestV2Error(f"{where}: screenshots must be a list of at most 4 relative image paths")
        parsed_shots: List[str] = []
        for s in raw_shots:
            if not isinstance(s, str) or not _PREVIEW_PATH.match(s) or ".." in Path(s).parts:
                raise ManifestV2Error(f"{where}: each screenshot must be a relative image path")
            if s not in parsed_shots:
                parsed_shots.append(s)
        screenshots = tuple(parsed_shots)
    icon_file = ""
    if "icon_file" in raw:
        ic = raw["icon_file"]
        if not isinstance(ic, str) or not _PREVIEW_PATH.match(ic) or ".." in Path(ic).parts:
            raise ManifestV2Error(f"{where}: icon_file must be a relative png or webp path")
        if Path(ic).suffix.lower() not in {".png", ".webp"}:
            raise ManifestV2Error(f"{where}: icon_file must be a .png or .webp file")
        icon_file = ic

    renamed_from = ""
    renamed_from_keeps: Tuple[str, ...] = ()
    old_strings = ""
    old_widgets = ""
    name_key = ""
    description_key = ""
    css_prefix = ""
    tool_family = ""
    if is_first_party:
        try:
            renamed_from = rf.parse_renamed_from(cplug_id, raw.get(rf.FIELD), ID_PATTERN, RESERVED_IDS)
            renamed_from_keeps = rf.parse_keeps(cplug_id, raw.get(rf.KEEPS_FIELD), renamed_from)
        except rf.RenamedFromError as exc:
            raise ManifestV2Error(str(exc)) from exc
        old_strings = rf.kept_old_id(renamed_from, renamed_from_keeps, rf.KEEP_STRINGS)
        old_widgets = rf.kept_old_id(renamed_from, renamed_from_keeps, rf.KEEP_WIDGETS)
        name_key = raw.get("name_key", f"cplug.{cplug_id}.name")
        if not isinstance(name_key, str) or not rf.key_allowed(cplug_id, old_strings, name_key, "name"):
            raise ManifestV2Error(f"{where}: name_key must be cplug.{cplug_id}.name")
        description_key = raw.get("description_key", f"cplug.{cplug_id}.description")
        if not isinstance(description_key, str) or not rf.key_allowed(cplug_id, old_strings, description_key, "description"):
            raise ManifestV2Error(f"{where}: description_key must be cplug.{cplug_id}.description")
        css_prefix = raw.get("css_prefix", cplug_id)
        if not isinstance(css_prefix, str) or not _CSS.match(css_prefix):
            raise ManifestV2Error(f"{where}: css_prefix must match {_CSS.pattern}")
        tool_family = _parse_tool_family(cplug_id, raw.get("tool_family"))

    tier0, run_cmd, run_mode, entry = _parse_run(raw.get("run"), where)
    timers = _parse_timers(raw.get("timers"), where)
    webhooks = _parse_webhooks(raw.get("webhooks"), where)
    events_on, events_emit = _parse_events(raw.get("events"), where)
    services_provides, services_consumes = _parse_services(raw.get("services"), where)
    sub_events = tuple(
        e
        for e in events_on
        if e not in _FEED_EVENT_FAMILIES and not (e.startswith("webhook.") and e[8:] in webhooks)
    )
    extra_events = tuple(dict.fromkeys([*events_emit, *sub_events]))
    permissions, network, reasons, merged_consumes, merged_events = _parse_permissions(
        cplug_id,
        raw.get("permissions"),
        webhooks,
        eff_tier,
        where,
        extra_services=services_consumes,
        extra_events=extra_events,
    )
    channels = _parse_channels(raw.get("channels"), network, where)
    macros = _parse_macros(raw.get("macros"), where)
    harnesses = _parse_harnesses(raw.get("harnesses"), where)
    tools, mcp_tools = _parse_tools(
        raw.get("mcp"),
        where,
        allow_builtin_mcp=is_first_party,
        cplug_id=cplug_id,
        tool_family=tool_family,
    )
    ui = _parse_ui(
        raw.get("ui"),
        where,
        allow_builtin_ui=is_first_party,
        cplug_id=cplug_id,
        renamed_from=renamed_from,
        old_strings=old_strings,
        old_widgets=old_widgets,
        tier=eff_tier,
    )

    if tier0 and not is_first_party and (tools or mcp_tools or ui.routes or ui.has_routes or timers or services_provides):
        raise ManifestV2Error(
            f"{where}: Tier 0 plugin without [run] cannot declare [mcp].tools, [ui].routes, [timers], or [services].provides"
        )

    settings_schema_raw = raw.get("settings_schema", {"version": 1, "fields": {}})
    if not isinstance(settings_schema_raw, dict):
        raise ManifestV2Error(f"{where}: settings_schema must be an object")
    settings_schema = _json_clone(settings_schema_raw, f"{where}: settings_schema")
    _validate_settings_schema(settings_schema, where)

    settings_aliases: Dict[str, str] = {}
    legacy_ids: Dict[str, str] = {}
    mcp_tool_aliases: Dict[str, str] = {}
    widgets: Dict[str, Dict[str, Any]] = {}
    if is_first_party:
        settings_aliases = _parse_settings_aliases(cplug_id, raw.get("settings_aliases"), settings_schema)
        legacy_ids = _parse_legacy_ids(cplug_id, raw.get("legacy_ids"), settings_schema)
        mcp_tool_aliases = _parse_tool_aliases(cplug_id, raw.get("mcp_tool_aliases"), mcp_tools, tuple(legacy_ids))
        widgets = _parse_widgets(cplug_id, raw.get("widgets"), ui.widgets, eff_tier, old_widgets)

    raw_requires = raw.get("requires", [])
    if not isinstance(raw_requires, list) or not all(
        isinstance(r, str) and r and r != cplug_id and (not renamed_from or r != renamed_from) for r in raw_requires
    ):
        raise ManifestV2Error(f"{where}: requires must be a list of other plugin ids")
    if len(set(raw_requires)) != len(raw_requires):
        raise ManifestV2Error(f"{where}: requires names one entry twice")
    requires = tuple(raw_requires)
    raw_requires_core = raw.get("requires_core", [])
    if not isinstance(raw_requires_core, list) or not all(isinstance(c, str) and c for c in raw_requires_core):
        raise ManifestV2Error(f"{where}: requires_core must be a list of names")
    if len(set(raw_requires_core)) != len(raw_requires_core):
        raise ManifestV2Error(f"{where}: requires_core names one entry twice")
    unknown_core = [c for c in raw_requires_core if c not in CORE_FEATURES]
    if unknown_core:
        raise ManifestV2Error(f"{where}: requires_core contains unknown core feature(s) {unknown_core}")
    requires_core = tuple(raw_requires_core)

    try:
        ai_features = parse_ai_features(cplug_id, raw.get("ai_features", {}), permissions)
    except AiFeatureError as exc:
        raise ManifestV2Error(str(exc)) from exc
    try:
        owns = parse_ownership(cplug_id, raw.get("owns"), old_strings)
    except OwnershipError as exc:
        raise ManifestV2Error(str(exc)) from exc

    data_decl: Optional[Tuple[DataDecl, ...]] = None
    if "data" in raw:
        try:
            fields = set(settings_schema.get("fields", {})) if isinstance(settings_schema.get("fields"), dict) else set()
            data_decl = parse_data(raw["data"], fields)
        except DataDeclError as exc:
            raise ManifestV2Error(str(exc)) from exc

    return ManifestV2(
        schema=2,
        id=cplug_id,
        name=name,
        version=version,
        kind=kind,
        description=description,
        author=author,
        license=license_str,
        min_app_version=min_app,
        icon=icon,
        tier=eff_tier,
        default_enabled=default_enabled,
        tier0=tier0,
        run_cmd=run_cmd,
        run_mode=run_mode,
        entry=entry,
        permissions=permissions,
        permission_reasons=reasons,
        network=network,
        services_consumes=merged_consumes,
        services_provides=services_provides,
        events_allowed=merged_events,
        events_on=events_on,
        events_emit=events_emit,
        tools=tools,
        routes=ui.routes,
        views=ui.views,
        page=ui.page,
        topics=ui.topics,
        ui_meta=ui.ui_meta,
        ui_contribute=ui.ui_contribute,
        ui_slots=ui.ui_slots,
        timers=timers,
        webhooks=webhooks,
        channels=channels,
        macros=macros,
        harnesses=harnesses,
        settings_schema=settings_schema,
        data=data_decl,
        owns=owns,
        requires=requires,
        requires_core=requires_core,
        ai_features=ai_features,
        trust=trust,
        preview=preview,
        screenshots=screenshots,
        icon_file=icon_file,
        api_version=api_version,
        name_key=name_key,
        description_key=description_key,
        css_prefix=css_prefix,
        tool_family=tool_family,
        mcp_tool_aliases=mcp_tool_aliases,
        settings_aliases=settings_aliases,
        legacy_ids=legacy_ids,
        renamed_from=renamed_from,
        renamed_from_keeps=renamed_from_keeps,
        widgets=widgets,
        has_routes=ui.has_routes,
        ui_storage=ui.storage,
        mcp_tools=mcp_tools,
        tabs=ui.tabs,
        menu_links=ui.menu_links,
        ui_plugins=ui.plugins,
        ui_widgets=ui.widgets,
        page_section=ui.page_section,
        page_section_label_key=ui.page_section_label_key,
        page_section_icon=ui.page_section_icon,
    )


def load_manifest_v2(
    code_root: Path,
    *,
    expected_id: Optional[str] = None,
    tier: str = TIER_CATALOG,
    expected_tier: Optional[str] = None,
    allow_tier_override: bool = False,
) -> ManifestV2:
    raw, _filename = load_raw_v2(code_root)
    return parse_manifest_v2(
        raw,
        expected_id=expected_id,
        tier=tier,
        expected_tier=expected_tier,
        allow_tier_override=allow_tier_override,
    )

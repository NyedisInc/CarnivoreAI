
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

try:
    from src.core.widget_fits.rules import GRID_SIZE_NAMES
except ImportError:
    GRID_SIZE_NAMES = ("small", "wide", "tall", "medium", "large", "full")

if __package__:
    from . import renamed_from as rf
    from ._settings_schema_fallback import SettingsSchemaFallbackError, parse_schema_fallback
    from .network import FORBIDDEN_HEADER_PREFIXES, FORBIDDEN_HEADERS, NetworkDecl, normalize_host
    from .schema_check import SchemaSet
    from .tool_families import TOOL_FAMILIES, family_prefix
else:
    import renamed_from as rf  # type: ignore[no-redef]
    from _settings_schema_fallback import SettingsSchemaFallbackError, parse_schema_fallback  # type: ignore[no-redef]
    from network import FORBIDDEN_HEADER_PREFIXES, FORBIDDEN_HEADERS, NetworkDecl, normalize_host  # type: ignore[no-redef]
    from schema_check import SchemaSet  # type: ignore[no-redef]
    from tool_families import TOOL_FAMILIES, family_prefix  # type: ignore[no-redef]

TOOL_GATES = ("read", "inbox")
TRUST_UNRESTRICTED = "unrestricted"
VIEW_SURFACES = ("panel", "overlay")
VIEW_TYPES = {
    "html": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "js": "text/javascript; charset=utf-8",
    "png": "image/png",
    "svg": "image/svg+xml",
    "woff2": "font/woff2",
}

RESERVED_ROUTES = frozenset({"secrets", "restart", "kill", "purge", "grants", "ui"})
_ROUTE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_TIMER_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_WEBHOOK_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_SECRET_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_.:-]{1,63}$")
_SERVICE_REF = re.compile(r"^[a-z][a-z0-9_.:@-]{0,63}$")
_SLOT_NAME = re.compile(r"^[a-z][a-z0-9_.:-]{1,63}$")
_VIEW_FILE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*$")
_TOPIC_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,39}$")
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_BUILTIN_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_SECRET_REF = re.compile(r"\$SECRET:([A-Za-z][A-Za-z0-9_]{0,63})")

TOOL_DESCRIPTION_MAX = 1000
MAX_TOOLS = 32
MAX_ROUTES = 32
MAX_VIEWS = 8
MAX_VIEW_FILES = 64
MAX_TIMERS = 16
MIN_TIMER_SECONDS = 5
MAX_TIMER_SECONDS = 86400
MAX_WEBHOOKS = 16
MAX_CHANNELS = 16
MAX_MACROS = 16
MAX_MACRO_STEPS = 16
MAX_HARNESSES = 16
MAX_EVENTS = 32
MAX_SERVICES = 32
MAX_SLOTS = 32
MAX_FIT_W, MAX_FIT_H = 12, 12
_NAMED_UNITS = {"small": (1, 1), "wide": (2, 1), "tall": (2, 4), "medium": (4, 4), "large": (6, 5), "full": (12, 5)}
DEFAULT_VIEW_FITS = {"sizes": ["medium", "large", "full"], "min": {"w": 3, "h": 3}, "anySize": True}

_DROP = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_BREAKS = frozenset({"Zl", "Zp"})

_UI_PUBLIC_KEYS = frozenset({"routes", "views", "page", "topics", "session_badge", "sidebar_tab", "widget", "commands", "slots", "contribute", "popout", "dev_frame_prefixes"})
_UI_BUILTIN_KEYS = frozenset({"tabs", "menu_links", "page_section", "page_section_label_key", "page_section_icon", "plugins", "widgets", "storage"})
_UI_KEYS = _UI_PUBLIC_KEYS | _UI_BUILTIN_KEYS
_MCP_KEYS = frozenset({"tools"})
_EVENTS_KEYS = frozenset({"on", "emit"})
_SERVICES_KEYS = frozenset({"provides", "consumes"})
_TIMER_KEYS = frozenset({"every_seconds"})
_WEBHOOK_KEYS = frozenset({"hmac_secret", "header"})
_CHANNEL_KEYS = frozenset({"url", "method", "headers", "body_template", "label"})
_MACRO_KEYS = frozenset({"title", "label", "shortcut", "steps"})
_WIDGET_KEYS = frozenset({"id", "title", "sizes", "mode", "document", "ui_file", "fits", "instancing", "settings", "glance", "popout"})
_SIDEBAR_TAB_KEYS = frozenset({"id", "title", "icon", "popout", "mode", "view", "document", "ui_file", "multi", "popout_multi"})
_POPOUT_KEYS = frozenset({"enabled", "width", "height", "multi"})
_COMMAND_KEYS = frozenset({"id", "title", "shortcut", "steps"})
_TOOL_KEYS = frozenset({"name", "description", "gate", "inputSchema"})
_FITS_KEYS = frozenset({"sizes", "min", "anySize"})
MACRO_ACTIONS = frozenset({"notify.toast", "sessions.message", "http.fetch", "ui.invalidate", "storage.put"})


class ManifestV2Error(ValueError):
    pass


def clean_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    kept = (
        " " if (c in "\t\n\r" or unicodedata.category(c) in _BREAKS)
        else ("" if unicodedata.category(c) in _DROP else c)
        for c in value
    )
    return " ".join("".join(kept).split())[:limit]


def _int_in(value: Any, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _json_clone(value: Any, where: str) -> Any:
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ManifestV2Error(f"{where}: value must be strict JSON ({type(exc).__name__})") from exc


def _check_tool_text(value: Any, where: str) -> None:
    if isinstance(value, str):
        if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") and c not in "\t\n" for c in value):
            raise ManifestV2Error(f"{where}: tool text contains control or formatting characters")
    elif isinstance(value, dict):
        for k, v in value.items():
            _check_tool_text(k, where)
            _check_tool_text(v, where)
    elif isinstance(value, list):
        for v in value:
            _check_tool_text(v, where)


def _check_rel_path(path: str, where: str) -> str:
    if not path or path.startswith("/") or ".." in Path(path).parts or "\\" in path:
        raise ManifestV2Error(f"{where}: path {path!r} must stay inside plugin directory")
    return path


def _parse_timers(raw: Any, where: str) -> Dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(raw) > MAX_TIMERS:
        raise ManifestV2Error(f"{where}: [timers] must be a table of at most {MAX_TIMERS} timers")
    out: Dict[str, int] = {}
    for name, cfg in raw.items():
        if not isinstance(name, str) or not _TIMER_NAME.match(name):
            raise ManifestV2Error(f"{where}: timer name {name!r} must match {_TIMER_NAME.pattern}")
        if not isinstance(cfg, dict) or set(cfg) != _TIMER_KEYS:
            raise ManifestV2Error(f"{where}: timer {name!r} must specify every_seconds only")
        every = cfg["every_seconds"]
        if not _int_in(every, MIN_TIMER_SECONDS, MAX_TIMER_SECONDS):
            raise ManifestV2Error(f"{where}: timer {name!r} every_seconds must be {MIN_TIMER_SECONDS}..{MAX_TIMER_SECONDS}")
        out[name] = every
    return out


def _parse_webhooks(raw: Any, where: str) -> Dict[str, Dict[str, str]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(raw) > MAX_WEBHOOKS:
        raise ManifestV2Error(f"{where}: [webhooks] must be a table of at most {MAX_WEBHOOKS} webhooks")
    out: Dict[str, Dict[str, str]] = {}
    for name, cfg in raw.items():
        if not isinstance(name, str) or not _WEBHOOK_NAME.match(name):
            raise ManifestV2Error(f"{where}: webhook name {name!r} must match {_WEBHOOK_NAME.pattern}")
        if not isinstance(cfg, dict) or set(cfg) - _WEBHOOK_KEYS or "hmac_secret" not in cfg:
            raise ManifestV2Error(f"{where}: webhook {name!r} must specify hmac_secret (optional header)")
        secret = cfg["hmac_secret"]
        if not isinstance(secret, str) or not _SECRET_NAME.match(secret):
            raise ManifestV2Error(f"{where}: webhook {name!r} hmac_secret must match {_SECRET_NAME.pattern}")
        entry: Dict[str, str] = {"hmac_secret": secret}
        if "header" in cfg:
            hdr = cfg["header"]
            if not isinstance(hdr, str) or not _HEADER_NAME.match(hdr):
                raise ManifestV2Error(f"{where}: webhook {name!r} header is invalid")
            entry["header"] = hdr
        out[name] = entry
    return out


def _parse_tools(
    raw: Any,
    where: str,
    *,
    allow_builtin_mcp: bool = False,
    cplug_id: str = "",
    tool_family: str = "",
) -> Tuple[Tuple[Mapping[str, Any], ...], Tuple[str, ...]]:
    if raw is None:
        return (), ()
    if not isinstance(raw, dict) or set(raw) - _MCP_KEYS:
        raise ManifestV2Error(f"{where}: [mcp] may contain only {sorted(_MCP_KEYS)}")
    tools = raw.get("tools", [])
    if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
        raise ManifestV2Error(f"{where}: [mcp].tools must be a list of at most {MAX_TOOLS}")
    if tools and all(isinstance(t, str) for t in tools):
        if not allow_builtin_mcp:
            raise ManifestV2Error(f"{where}: tool must have name, description, gate (inputSchema optional)")
        if len(set(tools)) != len(tools):
            raise ManifestV2Error(f"{where}: [mcp].tools names one entry twice")
        prefixes = (f"{cplug_id}_",) + ((family_prefix(tool_family),) if tool_family else ())
        for tool in tools:
            for family in TOOL_FAMILIES:
                if family != tool_family and tool.startswith(family_prefix(family)):
                    raise ManifestV2Error(
                        f"{where}: [mcp].tools: {tool} is a {family} family name, which needs tool_family {family} "
                        f"granted to {cplug_id} in sdk/tool_families.py"
                    )
            if not tool.startswith(prefixes) or tool in prefixes or not _BUILTIN_TOOL_NAME.match(tool):
                named = " or ".join(f"{p}<verb>" for p in prefixes)
                raise ManifestV2Error(f"{where}: [mcp].tools: {tool} must be named {named}")
        return (), tuple(tools)
    seen = set()
    for tool in tools:
        if not isinstance(tool, dict) or not set(tool) <= _TOOL_KEYS or not {"name", "description", "gate"} <= set(tool):
            raise ManifestV2Error(f"{where}: tool must have name, description, gate (inputSchema optional)")
        if not isinstance(tool["name"], str) or not _TOOL_NAME.match(tool["name"]) or tool["name"] in seen:
            raise ManifestV2Error(f"{where}: tool name must match {_TOOL_NAME.pattern} and be unique")
        seen.add(tool["name"])
        if tool["gate"] not in TOOL_GATES:
            raise ManifestV2Error(f"{where}: tool gate must be one of {TOOL_GATES}")
        desc = tool["description"]
        if not isinstance(desc, str) or not desc.strip() or len(desc) > TOOL_DESCRIPTION_MAX:
            raise ManifestV2Error(f"{where}: tool description must be 1..{TOOL_DESCRIPTION_MAX} chars")
        if "inputSchema" in tool and not isinstance(tool["inputSchema"], dict):
            raise ManifestV2Error(f"{where}: inputSchema must be an object")
        _check_tool_text(tool, where)
    normalized: List[Dict[str, Any]] = []
    for t in tools:
        item = _json_clone(t, f"{where}: [mcp].tools")
        if not item.get("inputSchema"):
            item["inputSchema"] = {"type": "object"}
        normalized.append(item)
    return tuple(normalized), tuple(str(item["name"]) for item in normalized)


def _parse_events(raw: Any, where: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    if raw is None:
        return (), ()
    if not isinstance(raw, dict) or set(raw) - _EVENTS_KEYS:
        raise ManifestV2Error(f"{where}: [events] may contain only {sorted(_EVENTS_KEYS)}")
    on_raw = raw.get("on", [])
    emit_raw = raw.get("emit", [])
    for key, seq in (("on", on_raw), ("emit", emit_raw)):
        if (
            not isinstance(seq, list)
            or len(seq) > MAX_EVENTS
            or not all(isinstance(e, str) and _EVENT_NAME.match(e) for e in seq)
            or len(set(seq)) != len(seq)
        ):
            raise ManifestV2Error(f"{where}: [events].{key} must be a list of unique event names")
    return tuple(on_raw), tuple(emit_raw)


def _parse_services(raw: Any, where: str) -> Tuple[Tuple[Mapping[str, Any], ...], Tuple[str, ...]]:
    if raw is None:
        return (), ()
    if not isinstance(raw, dict) or set(raw) - _SERVICES_KEYS:
        raise ManifestV2Error(f"{where}: [services] may contain only {sorted(_SERVICES_KEYS)}")
    provides_raw = raw.get("provides", [])
    consumes_raw = raw.get("consumes", [])
    if not isinstance(provides_raw, list) or len(provides_raw) > MAX_SERVICES:
        raise ManifestV2Error(f"{where}: [services].provides must be a list of at most {MAX_SERVICES}")
    provides: List[Dict[str, Any]] = []
    seen_services: set[str] = set()
    for i, item in enumerate(provides_raw):
        if not isinstance(item, dict) or not {"name", "methods"} <= set(item) <= {"name", "methods", "schemas"}:
            raise ManifestV2Error(f"{where}: [services].provides[{i}] must declare name and methods (schemas optional)")
        if not isinstance(item["name"], str) or not _SERVICE_REF.match(item["name"]) or item["name"] in seen_services:
            raise ManifestV2Error(f"{where}: [services].provides[{i}].name is invalid or duplicate")
        seen_services.add(item["name"])
        methods = item["methods"]
        if (
            not isinstance(methods, list)
            or not methods
            or not all(isinstance(m, str) and _TOOL_NAME.match(m) for m in methods)
            or len(set(methods)) != len(methods)
        ):
            raise ManifestV2Error(f"{where}: [services].provides[{i}].methods must be a list of unique method names")
        entry: Dict[str, Any] = {"name": item["name"], "methods": list(methods)}
        if "schemas" in item:
            schemas_raw = item["schemas"]
            if not isinstance(schemas_raw, dict):
                raise ManifestV2Error(f"{where}: [services].provides[{i}].schemas must be a table mapping method names to schemas")
            method_set = set(methods)
            for mname, mschema in schemas_raw.items():
                if not isinstance(mname, str) or mname not in method_set or not isinstance(mschema, dict):
                    raise ManifestV2Error(f"{where}: [services].provides[{i}].schemas[{mname!r}] must name a declared method with a schema object")
            schemas_clean = _json_clone(schemas_raw, f"{where}: [services].provides[{i}].schemas")
            bad = SchemaSet(schemas_clean).check_keywords()
            if bad:
                raise ManifestV2Error(f"{where}: [services].provides[{i}].schemas has unsupported JSON Schema keywords: {bad}")
            for mname, mschema in schemas_clean.items():
                bad_schema = SchemaSet({mname: mschema}).check_schemas(allow_external_refs=False)
                if bad_schema:
                    raise ManifestV2Error(f"{where}: [services].provides[{i}].schemas[{mname!r}] has invalid JSON Schema: {bad_schema}")
            entry["schemas"] = schemas_clean
        provides.append(entry)
    if (
        not isinstance(consumes_raw, list)
        or len(consumes_raw) > MAX_SERVICES
        or not all(isinstance(s, str) and _SERVICE_REF.match(s) for s in consumes_raw)
        or len(set(consumes_raw)) != len(consumes_raw)
    ):
        raise ManifestV2Error(f"{where}: [services].consumes must be a unique list of at most {MAX_SERVICES} service refs")
    return tuple(provides), tuple(consumes_raw)


def _parse_fits(value: Any, where: str) -> Dict[str, Any]:
    if value is None:
        return {**DEFAULT_VIEW_FITS, "min": dict(DEFAULT_VIEW_FITS["min"]), "sizes": list(DEFAULT_VIEW_FITS["sizes"])}
    if not isinstance(value, dict) or set(value) - _FITS_KEYS or "sizes" not in value:
        raise ManifestV2Error(f"{where}: view fits needs sizes and may carry only {sorted(_FITS_KEYS)}")
    sizes = value["sizes"]
    if not isinstance(sizes, list) or not sizes or not all(isinstance(n, str) and n in GRID_SIZE_NAMES for n in sizes) or len(set(sizes)) != len(sizes):
        raise ManifestV2Error(f"{where}: view fits sizes invalid")
    ordered = [n for n in GRID_SIZE_NAMES if n in sizes]
    floor = {"w": min(_NAMED_UNITS[n][0] for n in ordered), "h": min(_NAMED_UNITS[n][1] for n in ordered)}
    low = value.get("min", floor)
    if not isinstance(low, dict) or set(low) != {"w", "h"} or not _int_in(low["w"], 1, MAX_FIT_W) or not _int_in(low["h"], 1, MAX_FIT_H):
        raise ManifestV2Error(f"{where}: view fits min invalid")
    if low["w"] > floor["w"] or low["h"] > floor["h"]:
        raise ManifestV2Error(f"{where}: view fits min exceeds smallest declared size")
    any_size = value.get("anySize", False)
    if not isinstance(any_size, bool):
        raise ManifestV2Error(f"{where}: view fits anySize must be bool")
    return {"sizes": ordered, "min": {"w": low["w"], "h": low["h"]}, "anySize": any_size}


def _parse_macro_steps(steps: Any, where: str) -> List[Dict[str, Any]]:
    if not isinstance(steps, list) or not steps or len(steps) > MAX_MACRO_STEPS:
        raise ManifestV2Error(f"{where}: steps must be a list of 1..{MAX_MACRO_STEPS} objects")
    out: List[Dict[str, Any]] = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ManifestV2Error(f"{where}: steps[{i}] must be an object")
        action = step.get("action") or step.get("method")
        if not isinstance(action, str) or action not in MACRO_ACTIONS:
            raise ManifestV2Error(f"{where}: steps[{i}].action must be one of {sorted(MACRO_ACTIONS)}")
        params = step.get("params", {})
        if not isinstance(params, dict):
            raise ManifestV2Error(f"{where}: steps[{i}].params must be an object")
        out.append({"action": action, "params": _json_clone(params, f"{where}.steps[{i}].params")})
    return out


def _parse_channels(raw: Any, network: NetworkDecl, where: str) -> Dict[str, Dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(raw) > MAX_CHANNELS:
        raise ManifestV2Error(f"{where}: [channels] must be a table of at most {MAX_CHANNELS} channels")
    declared_net = {h.host for h in network.network_hosts}
    declared_lan = {(lh.scheme, lh.host, lh.port) for lh in network.lan_hosts}
    declared_secrets = {s.name for s in network.secrets}
    out: Dict[str, Dict[str, Any]] = {}
    for name, cfg in raw.items():
        if not isinstance(name, str) or not _WEBHOOK_NAME.match(name):
            raise ManifestV2Error(f"{where}: channel name {name!r} must match {_WEBHOOK_NAME.pattern}")
        if not isinstance(cfg, dict) or set(cfg) - _CHANNEL_KEYS or "url" not in cfg:
            raise ManifestV2Error(f"{where}: channel {name!r} may carry only {sorted(_CHANNEL_KEYS)} and requires url")
        url = cfg["url"]
        if not isinstance(url, str) or not url.strip():
            raise ManifestV2Error(f"{where}: channel {name!r}.url must be a non-empty URL")
        parts = urlsplit(url)
        host = normalize_host(parts.hostname or "") if parts.hostname else ""
        try:
            raw_port = parts.port
        except ValueError as exc:
            raise ManifestV2Error(f"{where}: channel {name!r}.url has an invalid port") from exc
        port = raw_port if raw_port is not None else (443 if parts.scheme == "https" else (80 if parts.scheme == "http" else None))
        if parts.scheme not in ("https", "http") or not host or port is None or not (1 <= port <= 65535):
            raise ManifestV2Error(f"{where}: channel {name!r}.url is invalid")
        if parts.scheme == "https" and port == 443 and host in declared_net:
            pass
        elif (parts.scheme, host, port) in declared_lan:
            pass
        else:
            raise ManifestV2Error(f"{where}: channel {name!r} host {host!r} must be declared under [permissions].network or [permissions].lan")
        method = str(cfg.get("method", "POST")).upper()
        if method not in ("POST", "PUT", "PATCH"):
            raise ManifestV2Error(f"{where}: channel {name!r}.method must be POST, PUT, or PATCH")
        headers_raw = cfg.get("headers", {})
        if not isinstance(headers_raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers_raw.items()):
            raise ManifestV2Error(f"{where}: channel {name!r}.headers must map header names to strings")
        headers: Dict[str, str] = {}
        for hname, hval in headers_raw.items():
            if not _HEADER_NAME.match(hname) or hname.lower() in FORBIDDEN_HEADERS or hname.lower().startswith(FORBIDDEN_HEADER_PREFIXES):
                raise ManifestV2Error(f"{where}: channel {name!r} header {hname!r} is forbidden")
            if re.search(r"[\r\n\x00]", hval):
                raise ManifestV2Error(f"{where}: channel {name!r} header value contains control characters")
            for m in _SECRET_REF.finditer(hval):
                if m.group(1) not in declared_secrets:
                    raise ManifestV2Error(f"{where}: channel {name!r} references undeclared secret {m.group(1)!r}")
            headers[hname] = hval
        body_tpl = cfg.get("body_template", "")
        if isinstance(body_tpl, dict):
            body_tpl = json.dumps(_json_clone(body_tpl, f"{where}: channel {name!r}.body_template"))
        elif not isinstance(body_tpl, str) or len(body_tpl) > 8192:
            raise ManifestV2Error(f"{where}: channel {name!r}.body_template must be string or JSON object")
        entry: Dict[str, Any] = {"url": url, "method": method, "headers": headers, "body_template": body_tpl}
        if "label" in cfg:
            entry["label"] = clean_text(cfg["label"], 80)
        out[name] = entry
    return out


def _parse_macros(raw: Any, where: str) -> Dict[str, Dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(raw) > MAX_MACROS:
        raise ManifestV2Error(f"{where}: [macros] must be a table of at most {MAX_MACROS} macros")
    out: Dict[str, Dict[str, Any]] = {}
    for name, cfg in raw.items():
        if not isinstance(name, str) or not _ROUTE_NAME.match(name):
            raise ManifestV2Error(f"{where}: macro name {name!r} must match {_ROUTE_NAME.pattern}")
        if not isinstance(cfg, dict) or set(cfg) - _MACRO_KEYS or "steps" not in cfg:
            raise ManifestV2Error(f"{where}: macro {name!r} requires steps and only {sorted(_MACRO_KEYS)}")
        entry: Dict[str, Any] = {"steps": _parse_macro_steps(cfg["steps"], f"{where}.macros.{name}")}
        if "title" in cfg:
            entry["title"] = clean_text(cfg["title"], 80)
        if "label" in cfg:
            entry["label"] = clean_text(cfg["label"], 80)
        if "shortcut" in cfg:
            if not isinstance(cfg["shortcut"], str) or len(cfg["shortcut"]) > 32:
                raise ManifestV2Error(f"{where}: macro {name!r}.shortcut must be a short string")
            entry["shortcut"] = cfg["shortcut"]
        out[name] = entry
    return out


def _parse_harnesses(raw: Any, where: str) -> Tuple[str, ...]:
    if raw is None:
        return ()
    paths: List[str] = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        if set(raw) == {"files"} and isinstance(raw.get("files"), list):
            items = raw["files"]
        elif all(isinstance(v, str) for v in raw.values()):
            items = list(raw.values())
        else:
            raise ManifestV2Error(f"{where}: harnesses must be a list or table of relative .toml paths")
    else:
        raise ManifestV2Error(f"{where}: harnesses must be a list or table of relative .toml paths")
    if len(items) > MAX_HARNESSES:
        raise ManifestV2Error(f"{where}: at most {MAX_HARNESSES} harness files are allowed")
    seen = set()
    for p in items:
        if not isinstance(p, str) or not p.endswith(".toml"):
            raise ManifestV2Error(f"{where}: harness path {p!r} must be a relative .toml file")
        _check_rel_path(p, f"{where}: harnesses")
        if p in seen:
            raise ManifestV2Error(f"{where}: duplicate harness path {p!r}")
        seen.add(p)
        paths.append(p)
    return tuple(paths)


def _parse_popout_cfg(value: Any, where: str) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        if set(value) - _POPOUT_KEYS:
            raise ManifestV2Error(f"{where}: popout may carry only {sorted(_POPOUT_KEYS)}")
        if "enabled" in value and not isinstance(value["enabled"], bool):
            raise ManifestV2Error(f"{where}: popout.enabled must be a boolean")
        if "multi" in value and not isinstance(value["multi"], bool):
            raise ManifestV2Error(f"{where}: popout.multi must be a boolean")
        if "width" in value and not _int_in(value["width"], 200, 4096):
            raise ManifestV2Error(f"{where}: popout.width must be 200..4096")
        if "height" in value and not _int_in(value["height"], 200, 4096):
            raise ManifestV2Error(f"{where}: popout.height must be 200..4096")
        return _json_clone(value, where)
    raise ManifestV2Error(f"{where}: popout must be a boolean or object")


@dataclass(frozen=True)
class ParsedUi:
    routes: Tuple[str, ...] = ()
    has_routes: bool = False
    views: Tuple[Mapping[str, Any], ...] = ()
    page: Optional[Mapping[str, Any]] = None
    topics: Tuple[str, ...] = ()
    ui_meta: Dict[str, Any] = field(default_factory=dict)
    ui_contribute: Dict[str, Any] = field(default_factory=dict)
    ui_slots: Tuple[str, ...] = ()
    tabs: Tuple[str, ...] = ()
    menu_links: Tuple[str, ...] = ()
    plugins: Tuple[str, ...] = ()
    widgets: Tuple[str, ...] = ()
    storage: Optional[bool] = None
    page_section: str = ""
    page_section_label_key: str = ""
    page_section_icon: str = ""


def _unique_names(raw: Mapping[str, Any], key: str, where: str) -> Tuple[str, ...]:
    val = raw.get(key, [])
    if not isinstance(val, list) or not all(isinstance(v, str) and v for v in val) or len(set(val)) != len(val):
        raise ManifestV2Error(f"{where}: [ui].{key} must be a list of unique names")
    return tuple(val)


def _parse_views(views_raw: Any, where: str) -> List[Dict[str, Any]]:
    if views_raw is None:
        return []
    if not isinstance(views_raw, list) or len(views_raw) > MAX_VIEWS:
        raise ManifestV2Error(f"{where}: [ui].views must be a list of at most {MAX_VIEWS}")
    views: List[Dict[str, Any]] = []
    seen_views = set()
    for v in views_raw:
        if not isinstance(v, dict) or not {"name", "surfaces", "files"} <= set(v) <= {"name", "surfaces", "files", "fits", "popout"}:
            raise ManifestV2Error(f"{where}: view needs name, surfaces, files (fits, popout optional)")
        name, surfaces, files = v["name"], v["surfaces"], v["files"]
        if not isinstance(name, str) or not _ROUTE_NAME.match(name) or name in seen_views:
            raise ManifestV2Error(f"{where}: view name {name!r} invalid or duplicate")
        seen_views.add(name)
        if not isinstance(surfaces, list) or not surfaces or not all(isinstance(s, str) and s in VIEW_SURFACES for s in surfaces) or len(set(surfaces)) != len(surfaces):
            raise ManifestV2Error(f"{where}: view surfaces invalid")
        if not isinstance(files, list) or not files or len(files) > MAX_VIEW_FILES or not all(isinstance(f, str) for f in files) or len(set(files)) != len(files):
            raise ManifestV2Error(f"{where}: view files invalid")
        for f in files:
            if not isinstance(f, str) or len(f) > 120 or not _VIEW_FILE.match(f) or "." not in f or f.rsplit(".", 1)[-1] not in VIEW_TYPES:
                raise ManifestV2Error(f"{where}: view file {f!r} invalid")
        if "index.html" not in files:
            raise ManifestV2Error(f"{where}: view {name!r} must include index.html")
        view_entry: Dict[str, Any] = {"name": name, "surfaces": list(surfaces), "files": list(files), "fits": _parse_fits(v.get("fits"), where)}
        if "popout" in v:
            view_entry["popout"] = _parse_popout_cfg(v["popout"], f"{where}: [ui].views.{name}.popout")
        views.append(view_entry)
    return views


def _parse_ui(
    raw: Any,
    where: str,
    *,
    allow_builtin_ui: bool = False,
    cplug_id: str = "",
    renamed_from: str = "",
    old_strings: str = "",
    old_widgets: str = "",
    tier: str = "",
) -> ParsedUi:
    if raw is None:
        return ParsedUi(storage=False if allow_builtin_ui else None)
    allowed_keys = _UI_KEYS if allow_builtin_ui else _UI_PUBLIC_KEYS
    if not isinstance(raw, dict) or set(raw) - allowed_keys:
        raise ManifestV2Error(f"{where}: [ui] may contain only {sorted(allowed_keys)}")

    routes_raw = raw.get("routes", [])
    if isinstance(routes_raw, bool):
        if not allow_builtin_ui:
            raise ManifestV2Error(f"{where}: [ui].routes must be a unique list of at most {MAX_ROUTES}")
        has_routes = routes_raw
        routes_tuple: Tuple[str, ...] = ()
    else:
        if (
            not isinstance(routes_raw, list)
            or len(routes_raw) > MAX_ROUTES
            or not all(isinstance(r, str) for r in routes_raw)
            or len(set(routes_raw)) != len(routes_raw)
        ):
            raise ManifestV2Error(f"{where}: [ui].routes must be a unique list of at most {MAX_ROUTES}")
        for r in routes_raw:
            if not _ROUTE_NAME.match(r) or r in RESERVED_ROUTES:
                raise ManifestV2Error(f"{where}: [ui].routes invalid entry {r!r}")
        routes_tuple = tuple(routes_raw)
        has_routes = bool(routes_tuple)

    views = _parse_views(raw.get("views", []), where)

    view_names = {v["name"] for v in views}
    page: Optional[Dict[str, Any]] = None
    if raw.get("page") is not None:
        p = raw["page"]
        if isinstance(p, dict) and {"menu", "main"} <= set(p) <= {"menu", "main", "popout"} and all(isinstance(p[k], str) and p[k] in view_names for k in ("menu", "main")):
            page = {"menu": p["menu"], "main": p["main"]}
            if "popout" in p:
                page["popout"] = _parse_popout_cfg(p["popout"], f"{where}: [ui].page.popout")
        else:
            raise ManifestV2Error(f"{where}: [ui].page must specify declared menu and main views")

    topics_raw = raw.get("topics", [])
    if not isinstance(topics_raw, list) or not all(isinstance(t, str) and _TOPIC_NAME.match(t) for t in topics_raw) or len(set(topics_raw)) != len(topics_raw):
        raise ManifestV2Error(f"{where}: [ui].topics must be a unique list of valid topic names")

    slots_raw = raw.get("slots", [])
    if (
        not isinstance(slots_raw, list)
        or len(slots_raw) > MAX_SLOTS
        or not all(isinstance(s, str) and _SLOT_NAME.match(s) for s in slots_raw)
        or len(set(slots_raw)) != len(slots_raw)
    ):
        raise ManifestV2Error(f"{where}: [ui].slots must be a unique list of at most {MAX_SLOTS} valid slot names")

    contribute_raw = raw.get("contribute", {})
    if (
        not isinstance(contribute_raw, dict)
        or len(contribute_raw) > MAX_SLOTS
        or not all(
            isinstance(k, str)
            and _SLOT_NAME.match(k)
            and isinstance(v, list)
            and 1 <= len(v) <= MAX_SLOTS
            and all(isinstance(entry, dict) for entry in v)
            for k, v in contribute_raw.items()
        )
    ):
        raise ManifestV2Error(f"{where}: [ui.contribute] must map valid slot names to non-empty lists of objects")
    contribute_clean = _json_clone(contribute_raw, f"{where}: [ui.contribute]")

    if "widget" in raw:
        w = raw["widget"]
        if not isinstance(w, dict) or set(w) - _WIDGET_KEYS:
            raise ManifestV2Error(f"{where}: [ui].widget must be an object with keys from {sorted(_WIDGET_KEYS)}")
        if "ui_file" in w:
            if not isinstance(w["ui_file"], str) or not w["ui_file"].endswith(".json"):
                raise ManifestV2Error(f"{where}: [ui].widget.ui_file must be a relative .json path")
            _check_rel_path(w["ui_file"], f"{where}: [ui].widget.ui_file")
        if "document" in w:
            doc = _json_clone(w["document"], f"{where}: [ui].widget.document")
            if not isinstance(doc, dict) or doc.get("schema") not in (1, 2) or not isinstance(doc.get("root"), dict):
                raise ManifestV2Error(f"{where}: [ui].widget.document must be a schema 1 or 2 declarative UI document")
        if "popout" in w:
            _parse_popout_cfg(w["popout"], f"{where}: [ui].widget.popout")

    if "sidebar_tab" in raw:
        st = raw["sidebar_tab"]
        if not isinstance(st, dict) or set(st) - _SIDEBAR_TAB_KEYS:
            raise ManifestV2Error(f"{where}: [ui].sidebar_tab must be an object with keys from {sorted(_SIDEBAR_TAB_KEYS)}")
        if "id" in st and (not isinstance(st["id"], str) or not _ROUTE_NAME.match(st["id"])):
            raise ManifestV2Error(f"{where}: [ui].sidebar_tab.id must match {_ROUTE_NAME.pattern}")
        if "mode" in st and st["mode"] not in ("declarative", "view"):
            raise ManifestV2Error(f"{where}: [ui].sidebar_tab.mode must be 'declarative' or 'view'")
        if "view" in st and (not isinstance(st["view"], str) or (view_names and st["view"] not in view_names) or not _ROUTE_NAME.match(st["view"])):
            raise ManifestV2Error(f"{where}: [ui].sidebar_tab.view must name a declared view")
        if "ui_file" in st:
            if not isinstance(st["ui_file"], str) or not st["ui_file"].endswith(".json"):
                raise ManifestV2Error(f"{where}: [ui].sidebar_tab.ui_file must be a relative .json path")
            _check_rel_path(st["ui_file"], f"{where}: [ui].sidebar_tab.ui_file")
        if "document" in st:
            doc = _json_clone(st["document"], f"{where}: [ui].sidebar_tab.document")
            if not isinstance(doc, dict) or doc.get("schema") not in (1, 2) or not isinstance(doc.get("root"), dict):
                raise ManifestV2Error(f"{where}: [ui].sidebar_tab.document must be a schema 1 or 2 declarative UI document")
        if "popout" in st:
            _parse_popout_cfg(st["popout"], f"{where}: [ui].sidebar_tab.popout")
        for bool_k in ("multi", "popout_multi"):
            if bool_k in st and not isinstance(st[bool_k], bool):
                raise ManifestV2Error(f"{where}: [ui].sidebar_tab.{bool_k} must be a boolean")

    if "popout" in raw:
        _parse_popout_cfg(raw["popout"], f"{where}: [ui].popout")

    if "commands" in raw:
        cmds = raw["commands"]
        if not isinstance(cmds, list) or len(cmds) > MAX_MACROS:
            raise ManifestV2Error(f"{where}: [ui].commands must be a list of at most {MAX_MACROS}")
        seen_cmds = set()
        for idx, cmd in enumerate(cmds):
            if not isinstance(cmd, dict) or set(cmd) - _COMMAND_KEYS or not isinstance(cmd.get("id"), str) or not _ROUTE_NAME.match(cmd["id"]):
                raise ManifestV2Error(f"{where}: [ui].commands[{idx}] invalid")
            if cmd["id"] in seen_cmds:
                raise ManifestV2Error(f"{where}: [ui].commands[{idx}] duplicate id {cmd['id']!r}")
            seen_cmds.add(cmd["id"])
            if "steps" in cmd:
                _parse_macro_steps(cmd["steps"], f"{where}: [ui].commands[{idx}]")

    if "dev_frame_prefixes" in raw:
        if tier != "dev":
            raise ManifestV2Error(f"{where}: [ui].dev_frame_prefixes is only permitted when tier == 'dev'")
        prefixes = raw["dev_frame_prefixes"]
        if (
            not isinstance(prefixes, list)
            or len(prefixes) > MAX_ROUTES
            or not all(isinstance(p, str) for p in prefixes)
            or len(set(prefixes)) != len(prefixes)
        ):
            raise ManifestV2Error(f"{where}: [ui].dev_frame_prefixes must be a unique list of at most {MAX_ROUTES} prefixes")
        for prefix in prefixes:
            segments = prefix.split("/")[1:-1]
            if (
                not prefix
                or not prefix.startswith("/")
                or not prefix.endswith("/")
                or "//" in prefix
                or ".." in prefix
                or "%" in prefix
                or "?" in prefix
                or "#" in prefix
                or "\\" in prefix
                or any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in prefix)
                or not segments
                or any(seg in ("", ".", "..") for seg in segments)
            ):
                raise ManifestV2Error(f"{where}: [ui].dev_frame_prefixes entry {prefix!r} is invalid")

    ui_meta = {
        k: _json_clone(raw[k], f"{where}: [ui].{k}")
        for k in ("session_badge", "sidebar_tab", "widget", "commands", "slots", "popout", "dev_frame_prefixes")
        if k in raw
    }
    if not allow_builtin_ui:
        return ParsedUi(
            routes=routes_tuple,
            has_routes=has_routes,
            views=tuple(views),
            page=page,
            topics=tuple(topics_raw),
            ui_meta=ui_meta,
            ui_contribute=contribute_clean,
            ui_slots=tuple(slots_raw),
            storage=None,
        )

    tabs = _unique_names(raw, "tabs", where)
    menu_links = _unique_names(raw, "menu_links", where)
    for key, entries in (("tabs", tabs), ("menu_links", menu_links)):
        for name in entries:
            if not rf.tab_allowed(cplug_id, renamed_from, name):
                raise ManifestV2Error(f"{where}: [ui].{key}: {name} must be {cplug_id} or start with {cplug_id}-")
    plugins = _unique_names(raw, "plugins", where)
    widgets = _unique_names(raw, "widgets", where)
    for name in widgets:
        if not _NAME.match(rf.bare_widget_name(old_widgets, name)):
            raise ManifestV2Error(f"{where}: [ui].widgets: {name} is not a valid name")
    section = raw.get("page_section", "")
    if not isinstance(section, str):
        raise ManifestV2Error(f"{where}: [ui].page_section must be a string")
    if section and (not _NAME.match(section) or not tabs):
        raise ManifestV2Error(f"{where}: [ui].page_section must be a lowercase id and needs at least one tab")
    label_key = raw.get("page_section_label_key", "")
    section_icon = raw.get("page_section_icon", "")
    if not isinstance(label_key, str) or not isinstance(section_icon, str):
        raise ManifestV2Error(f"{where}: [ui].page_section_label_key and page_section_icon must be strings")
    if section:
        if not label_key.startswith(rf.string_prefixes(cplug_id, old_strings)):
            raise ManifestV2Error(f"{where}: [ui].page_section_label_key must be a catalog key starting cplug.{cplug_id}.")
        if not _NAME.match(section_icon):
            raise ManifestV2Error(f"{where}: [ui].page_section_icon must be an icon name")
    elif label_key or section_icon:
        raise ManifestV2Error(f"{where}: [ui].page_section_label_key and page_section_icon need page_section")
    ui_storage = raw.get("storage", False)
    if not isinstance(ui_storage, bool):
        raise ManifestV2Error(f"{where}: [ui].storage must be true or false")
    return ParsedUi(
        routes=routes_tuple,
        has_routes=has_routes,
        views=tuple(views),
        page=page,
        topics=tuple(topics_raw),
        ui_meta=ui_meta,
        ui_contribute=contribute_clean,
        ui_slots=tuple(slots_raw),
        tabs=tabs,
        menu_links=menu_links,
        plugins=plugins,
        widgets=widgets,
        storage=ui_storage,
        page_section=section,
        page_section_label_key=label_key,
        page_section_icon=section_icon,
    )


def _validate_settings_schema(settings_schema: Dict[str, Any], where: str) -> None:
    try:
        from src.core.item_settings_schema import SettingsSchemaError, parse_schema  # noqa: PLC0415
    except ModuleNotFoundError:
        try:
            parse_schema_fallback(settings_schema)
        except SettingsSchemaFallbackError as exc:
            raise ManifestV2Error(f"{where}: settings_schema: {exc}") from exc
        return
    try:
        parse_schema(settings_schema)
    except SettingsSchemaError as exc:
        raise ManifestV2Error(f"{where}: settings_schema: {exc}") from exc

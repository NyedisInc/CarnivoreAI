
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Tuple

from src.cplugs.host.identity import RESERVED_ROUTES
from src.cplugs.host.preview_check import PreviewError, check_preview_path, read_preview
from src.cplugs.runtime.process import FEED_GRANTS
from src.cplugs.runtime.integrity import IntegrityError, tree_digest
from src.cplugs.sdk.manifest import ID_PATTERN, SIDECAR_FILE, Ownership, Surfaces
from src.cplugs.sdk.network import NetworkDecl, NetworkDeclError, parse_network
from src.cplugs.sdk.permission_registry import TIER_CATALOG, is_declarable, may_ask
from src.core.widget_fits.rules import GRID_SIZE_NAMES

MANIFEST_FILE = "cplug.json"
TOOL_GATES = ("read", "inbox")
NAME_MAX = 60
DESCRIPTION_MAX = 400
TOOL_DESCRIPTION_MAX = 1000
MAX_TOOLS = 32
_TOP_KEYS = frozenset({"schema", "id", "name", "description", "version", "entry", "tools", "permissions", "default_enabled",
                       "network_hosts", "lan_hosts", "secrets", "routes", "subscriptions", "views", "trust", "preview"})
TRUST_UNRESTRICTED = "unrestricted"
MAX_ROUTES = 32
_ROUTE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_TOOL_KEYS = frozenset({"name", "description", "gate", "inputSchema"})
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_ENTRY = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*\.py$")
_DROP = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_BREAKS = frozenset({"Zl", "Zp"})


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


def clean_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    kept = (" " if (c in "\t\n\r" or unicodedata.category(c) in _BREAKS) else ("" if unicodedata.category(c) in _DROP else c) for c in value)
    return " ".join("".join(kept).split())[:limit]


def _text(raw: Mapping[str, Any], key: str, limit: int, where: str) -> str:
    text = clean_text(raw.get(key), limit)
    if not text:
        raise SidecarManifestError(f"{where}: {key} must be a non-empty string")
    return text


def _check_tool_text(value: Any, where: str) -> None:
    if isinstance(value, str):
        if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") and c not in "\t\n" for c in value):
            raise SidecarManifestError(f"{where}: a tool string may not hold control or invisible formatting characters")
    elif isinstance(value, dict):
        for k, v in value.items():
            _check_tool_text(k, where)
            _check_tool_text(v, where)
    elif isinstance(value, list):
        for v in value:
            _check_tool_text(v, where)


def _tools(raw: Any, where: str) -> Tuple[Mapping[str, Any], ...]:
    if not isinstance(raw, list) or len(raw) > MAX_TOOLS:
        raise SidecarManifestError(f"{where}: tools must be a list of at most {MAX_TOOLS}")
    seen = set()
    for tool in raw:
        if not isinstance(tool, dict) or not set(tool) <= _TOOL_KEYS or not {"name", "description", "gate"} <= set(tool):
            raise SidecarManifestError(f"{where}: a tool needs name, description and gate (inputSchema optional) and nothing else")
        if not isinstance(tool["name"], str) or not _TOOL_NAME.match(tool["name"]) or tool["name"] in seen:
            raise SidecarManifestError(f"{where}: a tool name must match {_TOOL_NAME.pattern} and be unique")
        seen.add(tool["name"])
        if tool["gate"] not in TOOL_GATES:
            raise SidecarManifestError(f"{where}: tool gate must be one of {TOOL_GATES}")
        description = tool["description"]
        if not isinstance(description, str) or not description.strip() or len(description) > TOOL_DESCRIPTION_MAX:
            raise SidecarManifestError(f"{where}: a tool description must be 1 to {TOOL_DESCRIPTION_MAX} characters")
        if "inputSchema" in tool and not isinstance(tool["inputSchema"], dict):
            raise SidecarManifestError(f"{where}: inputSchema must be an object")
        _check_tool_text(tool, where)
    return tuple(json.loads(json.dumps(t)) for t in raw)


def _permissions(raw: Any, where: str) -> Tuple[str, ...]:
    if raw is None:
        return ()
    names = raw.get("app", []) if isinstance(raw, dict) and set(raw) <= {"app"} else None
    if not isinstance(names, list) or not all(isinstance(p, str) for p in names) or len(set(names)) != len(names):
        raise SidecarManifestError(f"{where}: permissions must be an object with a list of unique names under app only")
    for p in names:
        if not is_declarable(p) or not may_ask(p, TIER_CATALOG):
            raise SidecarManifestError(f"{where}: a catalog plugin may not ask for {p[:80]!r}")
    return tuple(names)


def _routes(value: Any, where: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_ROUTES:
        raise SidecarManifestError(f"{where}: routes must be a list of at most {MAX_ROUTES} names")
    for name in value:
        if not isinstance(name, str) or not _ROUTE_NAME.match(name) or name in RESERVED_ROUTES:
            raise SidecarManifestError(f"{where}: routes holds a name that is not a lowercase word or is a host route name")
    if len(set(value)) != len(value):
        raise SidecarManifestError(f"{where}: routes holds a duplicate name")
    return tuple(value)


MAX_VIEWS = 8
MAX_VIEW_FILES = 64
VIEW_SURFACES = ("panel", "overlay")
VIEW_TYPES = {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8", "js": "text/javascript; charset=utf-8", "png": "image/png",
              "svg": "image/svg+xml", "woff2": "font/woff2"}
_VIEW_FILE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*$")


_FITS_KEYS = frozenset({"sizes", "min", "anySize"})
MAX_FIT_W, MAX_FIT_H = 12, 12
_NAMED_UNITS = {"small": (1, 1), "wide": (2, 1), "tall": (2, 4), "medium": (4, 4), "large": (6, 5), "full": (12, 5)}
DEFAULT_VIEW_FITS = {"sizes": ["medium", "large", "full"], "min": {"w": 3, "h": 3}, "anySize": True}


def _int_in(value: Any, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _fits(value: Any, where: str) -> Mapping[str, Any]:
    if value is None:
        return {**DEFAULT_VIEW_FITS, "min": dict(DEFAULT_VIEW_FITS["min"]), "sizes": list(DEFAULT_VIEW_FITS["sizes"])}
    if not isinstance(value, dict) or not set(value) <= _FITS_KEYS or "sizes" not in value:
        raise SidecarManifestError(f"{where}: view fits needs sizes and may carry only {sorted(_FITS_KEYS)}")
    sizes = value["sizes"]
    if not isinstance(sizes, list) or not sizes or len(set(map(str, sizes))) != len(sizes) or any(n not in GRID_SIZE_NAMES for n in sizes):
        raise SidecarManifestError(f"{where}: view fits sizes must be a unique non-empty list from {list(GRID_SIZE_NAMES)}")
    ordered = [n for n in GRID_SIZE_NAMES if n in sizes]
    floor = {"w": min(_NAMED_UNITS[n][0] for n in ordered), "h": min(_NAMED_UNITS[n][1] for n in ordered)}
    low = value.get("min", floor)
    if not isinstance(low, dict) or set(low) != {"w", "h"} or not _int_in(low["w"], 1, MAX_FIT_W) or not _int_in(low["h"], 1, MAX_FIT_H):
        raise SidecarManifestError(f"{where}: view fits min must be whole grid units {{w: 1 to {MAX_FIT_W}, h: 1 to {MAX_FIT_H}}}")
    if low["w"] > floor["w"] or low["h"] > floor["h"]:
        raise SidecarManifestError(f"{where}: view fits min {low['w']} x {low['h']} is larger than the smallest declared size {floor['w']} x {floor['h']}")
    any_size = value.get("anySize", False)
    if not isinstance(any_size, bool):
        raise SidecarManifestError(f"{where}: view fits anySize must be true or false")
    return {"sizes": ordered, "min": {"w": low["w"], "h": low["h"]}, "anySize": any_size}


def _views(value: Any, where: str) -> Tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_VIEWS:
        raise SidecarManifestError(f"{where}: views must be a list of at most {MAX_VIEWS}")
    out, seen = [], set()
    for v in value:
        if not isinstance(v, dict) or not {"name", "surfaces", "files"} <= set(v) <= {"name", "surfaces", "files", "fits"}:
            raise SidecarManifestError(f"{where}: a view needs name, surfaces and files, may carry fits, and nothing else")
        name, surfaces, files = v["name"], v["surfaces"], v["files"]
        if not isinstance(name, str) or not _ROUTE_NAME.match(name) or name in seen:
            raise SidecarManifestError(f"{where}: a view name must be a unique lowercase word")
        seen.add(name)
        if not isinstance(surfaces, list) or not surfaces or len(set(surfaces)) != len(surfaces) or any(s not in VIEW_SURFACES for s in surfaces):
            raise SidecarManifestError(f"{where}: view surfaces must be a unique list from {VIEW_SURFACES}")
        if not isinstance(files, list) or not files or len(files) > MAX_VIEW_FILES or len(set(files)) != len(files):
            raise SidecarManifestError(f"{where}: view files must be a list of 1 to {MAX_VIEW_FILES} unique paths")
        for f in files:
            if not isinstance(f, str) or len(f) > 120 or not _VIEW_FILE.match(f) or f.rsplit(".", 1)[-1] not in VIEW_TYPES or "." not in f:
                raise SidecarManifestError(f"{where}: a view file is a plain relative path ending in {sorted(VIEW_TYPES)}")
        if "index.html" not in files:
            raise SidecarManifestError(f"{where}: a view must list index.html")
        out.append({"name": name, "surfaces": list(surfaces), "files": list(files), "fits": _fits(v.get("fits"), where)})
    return tuple(out)


def _subscriptions(value: Any, where: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(f, str) or f not in FEED_GRANTS for f in value) or len(set(value)) != len(value):
        raise SidecarManifestError(f"{where}: subscriptions must be a list of unique known event families")
    return tuple(value)


def parse_sidecar_manifest(raw: Any, item_name: str, code_digest: str) -> SidecarManifest:
    where = f"cplug {item_name}"
    if not isinstance(raw, dict) or raw.get("schema") != 1:
        raise SidecarManifestError(f"{where}: cplug.json must be an object with schema 1")
    unknown = sorted(set(raw) - _TOP_KEYS)
    if unknown:
        raise SidecarManifestError(f"{where}: unknown keys {[k[:40] for k in unknown]}")
    if raw.get("id") != item_name or not ID_PATTERN.match(item_name):
        raise SidecarManifestError(f"{where}: id must equal the catalog name and match {ID_PATTERN.pattern}")
    if not isinstance(raw.get("version"), str) or not _SEMVER.match(raw["version"]):
        raise SidecarManifestError(f"{where}: version must be major.minor.patch")
    entry = raw.get("entry")
    if not isinstance(entry, str) or len(entry) > 200 or not _ENTRY.match(entry) or ".." in entry.split("/"):
        raise SidecarManifestError(f"{where}: entry must be a relative .py path inside the code folder")
    permissions = _permissions(raw.get("permissions"), where)
    try:
        network = parse_network(item_name, raw, permissions)
    except NetworkDeclError as exc:
        raise SidecarManifestError(f"{where}: {exc}") from exc
    if "default_enabled" in raw and not isinstance(raw["default_enabled"], bool):
        raise SidecarManifestError(f"{where}: default_enabled must be a boolean")
    trust = raw.get("trust", "")
    if "trust" in raw and trust != TRUST_UNRESTRICTED:
        raise SidecarManifestError(f"{where}: trust, when present, must be exactly \"{TRUST_UNRESTRICTED}\"")
    preview = ""
    if "preview" in raw:
        try:
            preview = check_preview_path(raw["preview"])
        except PreviewError as exc:
            raise SidecarManifestError(f"{where}: {exc}") from exc
    return SidecarManifest(
        id=item_name, name=_text(raw, "name", NAME_MAX, where), description=_text(raw, "description", DESCRIPTION_MAX, where),
        version=raw["version"], entry=entry, tools=_tools(raw.get("tools", []), where), permissions=permissions, network=network,
        code_digest=code_digest, routes=_routes(raw.get("routes"), where),
        subscriptions=_subscriptions(raw.get("subscriptions"), where), views=_views(raw.get("views"), where), trust=trust, preview=preview)


def sidecar_reasons(doc: Any) -> Mapping[str, str]:
    perms = doc.get("permissions", []) if isinstance(doc, dict) else []
    return {p["name"]: p["reason"] for p in perms if isinstance(p, dict) and isinstance(p.get("name"), str) and "reason" in p}


def with_sidecar_facts(manifest: SidecarManifest, code_root: Path) -> SidecarManifest:
    try:
        side = json.loads((Path(code_root) / SIDECAR_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return manifest
    if not isinstance(side, dict):
        return manifest
    return replace(manifest, author=clean_text(side.get("author", ""), 80), icon=clean_text(side.get("icon", ""), 40) or manifest.icon,
                   min_app_version=clean_text(side.get("min_app_version", ""), 20),
                   permission_reasons={k: clean_text(v, 300) for k, v in sidecar_reasons(side).items()})


def load_sidecar_manifest(code_root: Path, item_name: str) -> SidecarManifest:
    """Read, digest and validate the manifest in ``code_root``. Blocking. Output: SidecarManifest. Raises SidecarManifestError.

    Description: the digest is taken first and over the whole tree (``tree_digest`` refuses symlinks and bytecode); the entry
      file must exist as a regular file.
    Example: load_sidecar_manifest(Path(state) / "cplug-code" / "clock", "clock").entry -> "main.py"
    """
    try:
        digest = tree_digest(code_root)
        raw = json.loads((Path(code_root) / MANIFEST_FILE).read_text(encoding="utf-8"))
    except (IntegrityError, OSError, ValueError) as exc:
        raise SidecarManifestError(f"cplug {item_name}: the code folder cannot be read ({type(exc).__name__})") from exc
    manifest = parse_sidecar_manifest(raw, item_name, digest)
    entry = Path(code_root) / manifest.entry
    if not entry.is_file() or entry.is_symlink():
        raise SidecarManifestError(f"cplug {item_name}: entry is not a file in the code folder")
    if manifest.preview:
        try:
            read_preview(code_root, manifest.preview)
        except PreviewError as exc:
            raise SidecarManifestError(f"cplug {item_name}: {exc}") from exc
    return manifest

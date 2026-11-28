
from __future__ import annotations

import json
import os
import posixpath
import re
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core import message_model_secrets
from src.core.catalog import publish_prepare, submission_preview
from src.core.catalog import submission_rules as rules
from src.core.skills.plugin_safe_subset import CODE_MANIFEST_KEYS, mcp_problems, plugin_declares_nonmcp_code
from src.plugins.host import install_gates
from src.plugins.host.plugin_manifest import SidecarManifestError, validate_v2_files
from src.plugins.host.preview_check import PreviewError, read_preview
from src.plugins.host.sideload_copy import DEV_SKIP_DIRS
from src.plugins.sdk import api_contract
from src.plugins.sdk.cplug_validate import (
    ID_PATTERN as CPLUG_ID_PATTERN,
    OTHER_KIND_MANIFESTS as CPLUG_OTHER_KIND_MANIFESTS,
    RESERVED_IDS as CPLUG_RESERVED_IDS,
    validate_v2_folder_files,
)
from src.plugins.sdk.manifest_v2 import ManifestV2Error, TIER_CATALOG, TIER_LOCAL, TOML_FILE, has_v2_manifest, load_raw_v2, parse_manifest_v2

logger = structlog.get_logger()

KIND_THEME = "theme"
KIND_PLUGIN = "plugin"
KIND_MOD = "mod"
KIND_CPLUG = "cplug"
CPLUG_MANIFEST = "cplug.json"
CPLUG_SIDECAR = "carnivore.json"
HOOKS_MANIFEST = "hooks/hooks.json"
THEME_MANIFEST = "theme.json"
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"

_THEME_SCRIPT_EXT = (".js", ".mjs", ".cjs", ".svg", ".html", ".htm", ".css")
_THEME_IMAGE_EXT = (".webp", ".png", ".jpg")
_THEME_KEYS = frozenset(
    {"id", "name", "description", "author", "version", "cssVars", "xterm", "background", "characters", "effects", "mascot"}
)
_PLUGIN_FORBIDDEN_SEGMENTS = frozenset({".claude", "node_modules"})
_PLUGIN_ALLOWED_DOT_ROOTS = frozenset({".claude-plugin", ".mcp.json", ".lsp.json"})
_PLUGIN_FORBIDDEN_NAMES = re.compile(
    r"^(?:\.mcp\.json|\.lsp\.json|settings(?:\.local)?\.json|hooks\.json)$", re.IGNORECASE
)
_PLUGIN_TEXT_EXT = (".md", ".txt", ".json", ".yaml", ".yml")
_PLUGIN_ROOT_DOC = re.compile(r"^(?:readme|license)(?:\.md|\.txt)?$", re.IGNORECASE)
_CAPS = {
    KIND_THEME: (32, 512 * 1024, 1024 * 1024),
    KIND_PLUGIN: (500, rules.MAX_FILE_BYTES, 1024 * 1024),
    KIND_MOD: (200, rules.MAX_FILE_BYTES, 1024 * 1024),
    KIND_CPLUG: (install_gates.MAX_MEMBERS, install_gates.MAX_FILE_BYTES, install_gates.MAX_TOTAL_BYTES),
}
_CPLUG_SOURCE_SUFFIXES = frozenset({".py", ".js", ".html", ".css", ".svg"})
_SOURCE_DETECTORS = tuple(d for d in message_model_secrets.ALL_DETECTORS
                          if d != message_model_secrets.DETECTOR_HIGH_ENTROPY_ASSIGNMENT)
_MOD_MANIFEST_KEYS = frozenset(
    {"name", "version", "description", "author", "homepage", "repository", "license", "keywords", "types"}
)
_MOD_SOURCE_EXT = (".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs", ".jsx")
_MOD_FILE_EXT = _MOD_SOURCE_EXT + (".json", ".md")
_MOD_MAX_LISTED = 10

_MOD_GENERATED_DIR = ".claude-plugin/types/"


def _walk(folder: Path) -> List[str]:
    found: List[str] = []
    for root, dirs, files in os.walk(folder, followlinks=False):
        rel = Path(root).relative_to(folder)
        found.extend((rel / name).as_posix() for name in files + [d for d in dirs if os.path.islink(Path(root) / d)])
    return sorted(found)


def _walk_v2(folder: Path) -> List[str]:
    found: List[str] = []
    for root, dirs, files in os.walk(folder, followlinks=False):
        rel = Path(root).relative_to(folder)
        skip = DEV_SKIP_DIRS | ({"tests"} if rel == Path(".") else set())
        for d in dirs:
            if d not in skip and os.path.islink(Path(root) / d):
                found.append((rel / d).as_posix())
        dirs[:] = sorted(d for d in dirs if d not in skip)
        for name in sorted(files):
            if name == ".DS_Store" or name.startswith("._") or name.endswith((".pyc", ".pyo")):
                continue
            found.append((rel / name).as_posix())
    return sorted(found)


def _refuse(prepared: publish_prepare.Prepared, code: str, detail: str, path: Optional[str]) -> None:
    prepared.refusals.append(rules.Refusal(code, detail, path))


def _read_all(folder: Path, paths: List[str], prepared: publish_prepare.Prepared, kind: str) -> Dict[str, bytes]:
    max_members, max_file, max_total = _CAPS[kind]
    if len(paths) > max_members:
        _refuse(prepared, rules.SUBMISSION_INVALID, f"a {kind} may carry at most {max_members} files", None)
        return {}
    read: Dict[str, bytes] = {}
    for relpath in paths:
        try:
            content = publish_prepare._read_member(folder, relpath, max_file)
        except OSError as exc:
            _refuse(prepared, rules.SUBMISSION_INVALID, f"this file could not be read: {exc.strerror or exc}", relpath)
            continue
        if len(content) > max_file:
            _refuse(prepared, rules.SUBMISSION_INVALID, f"this file is over the {max_file // 1024} KiB limit", relpath)
            continue
        detectors = _SOURCE_DETECTORS if kind == KIND_CPLUG and Path(relpath).suffix.lower() in _CPLUG_SOURCE_SUFFIXES else None
        found = sorted({f.detector for f in message_model_secrets.scan_text(content.decode("utf-8", errors="replace"), detectors=detectors)})
        if found:
            _refuse(prepared, rules.SUBMISSION_INVALID,
                    f"this file looks like it holds a credential ({', '.join(found)}); remove it before publishing", relpath)
        read[relpath] = content
        prepared.members.append((relpath, content))
        prepared.total_bytes += len(content)
    if prepared.total_bytes > max_total:
        _refuse(prepared, rules.BODY_TOO_LARGE, f"a {kind} may total at most {max_total // 1024} KiB", None)
    return read


def _check_theme(paths: List[str], read: Dict[str, bytes], prepared: publish_prepare.Prepared) -> None:
    for path in paths:
        parts = path.split("/")
        if any(p.startswith(".") for p in parts) or "node_modules" in parts:
            _refuse(prepared, rules.SUBMISSION_INVALID, "a theme may not carry hidden files or node_modules", path)
    raw = read.get(THEME_MANIFEST)
    if raw is None:
        _refuse(prepared, rules.SUBMISSION_INVALID, "the folder carries no theme.json", None)
        return
    manifest = _json_object(raw)
    if manifest is None:
        _refuse(prepared, rules.SUBMISSION_INVALID, "theme.json is not a json object", THEME_MANIFEST)
        return
    for key in sorted(set(manifest) - _THEME_KEYS):
        _refuse(prepared, rules.SUBMISSION_INVALID, f"theme.json may not carry the key {key!r}", THEME_MANIFEST)


def _plugin_path_allowed(path: str) -> bool:
    parts = path.split("/")
    if any(p.lower() in _PLUGIN_FORBIDDEN_SEGMENTS for p in parts):
        return False
    if path == PLUGIN_MANIFEST or path == ".mcp.json" or path == ".lsp.json":
        return True
    if parts[0] == ".claude-plugin":
        return not any(p.startswith(".") for p in parts[1:])
    if any(p.startswith(".") for p in parts):
        return False
    return True


def _check_plugin(folder: Path, paths: List[str], read: Dict[str, bytes], prepared: publish_prepare.Prepared) -> None:
    _ = folder
    for path in paths:
        if path == HOOKS_MANIFEST and path in read and b'"modules"' in read[path]:
            _refuse(prepared, "plugin_not_safe", "hook modules make a mod: declare kind mod", path)
        elif not _plugin_path_allowed(path):
            _refuse(prepared, "plugin_not_safe", "hidden files and node_modules are not allowed in a plugin", path)
    raw = read.get(PLUGIN_MANIFEST)
    manifest = _json_object(raw) if raw is not None else None
    if manifest is None:
        _refuse(prepared, rules.SUBMISSION_INVALID, "the folder carries no readable .claude-plugin/plugin.json", None)
        return
    for problem in mcp_problems(manifest, read.get(".mcp.json")):
        _refuse(prepared, "plugin_not_safe", f"an mcp server declaration is malformed: {problem}", PLUGIN_MANIFEST)
    name = manifest.get("name")
    if isinstance(name, str) and name:
        prepared.name = name


def is_mod_folder(folder: Path) -> bool:
    try:
        value = json.loads((folder / HOOKS_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(value, dict) and "modules" in value


def _mod_module_path(ref: Any) -> str:
    if not isinstance(ref, str) or not ref.startswith("./"):
        return ""
    path = posixpath.normpath(posixpath.join("hooks", ref))
    return "" if path.startswith("..") or path.startswith("/") else path


def _check_mod(paths: List[str], read: Dict[str, bytes], prepared: publish_prepare.Prepared) -> None:
    manifest = _json_object(read[PLUGIN_MANIFEST]) if PLUGIN_MANIFEST in read else None
    hooks = _json_object(read[HOOKS_MANIFEST]) if HOOKS_MANIFEST in read else None
    if manifest is None:
        _refuse(prepared, rules.SUBMISSION_INVALID, "the folder carries no readable .claude-plugin/plugin.json", None)
    if hooks is None:
        _refuse(prepared, rules.SUBMISSION_INVALID, "the folder carries no readable hooks/hooks.json", None)
    if manifest is None or hooks is None:
        return
    author = manifest.get("author")
    if not (isinstance(author, str) and author.strip()) and not (
        isinstance(author, dict) and isinstance(author.get("name"), str) and author["name"].strip()
    ):
        _refuse(prepared, rules.SUBMISSION_INVALID, "plugin.json needs an author", PLUGIN_MANIFEST)
    problems: List[str] = [f"{PLUGIN_MANIFEST} (key {str(k)[:40]})" for k in manifest if k not in _MOD_MANIFEST_KEYS]
    for key in ("homepage", "repository"):
        value = manifest.get(key)
        if value is not None and not (isinstance(value, str) and re.match(r"^https?://", value)):
            problems.append(f"{PLUGIN_MANIFEST} ({key} must be an http or https url)")
    if "types" in manifest and _mod_module_path_root(manifest["types"]) not in read:
        problems.append(f"{PLUGIN_MANIFEST} (types must name a file in the folder)")
    modules = hooks.get("modules")
    if set(hooks) != {"modules"} or not isinstance(modules, list) or not modules:
        problems.append(f'{HOOKS_MANIFEST} (must be exactly {{"modules": [...]}} with at least one entry)')
        modules = []
    for entry in modules:
        target = _mod_module_path(entry)
        if not target or target not in read:
            problems.append(f"{HOOKS_MANIFEST} (module {str(entry)[:60]} is not a ./ file inside the folder)")
        elif not target.lower().endswith(_MOD_SOURCE_EXT):
            problems.append(f"{HOOKS_MANIFEST} (module {target} is not a source file)")
    for path in paths:
        parts = path.split("/")
        if "node_modules" in parts or parts[-1].lower() == "package.json":
            problems.append(f"{path} (path not allowed)")
        elif path != PLUGIN_MANIFEST and any(part.startswith(".") for part in parts):
            problems.append(f"{path} (hidden path not allowed)")
    if problems:
        more = f"; and {len(problems) - _MOD_MAX_LISTED} more" if len(problems) > _MOD_MAX_LISTED else ""
        _refuse(prepared, "mod_not_safe", f"a mod may not carry: {'; '.join(problems[:_MOD_MAX_LISTED])}{more}", None)
    name = manifest.get("name")
    if isinstance(name, str) and name:
        prepared.name = name


def _mod_module_path_root(ref: Any) -> str:
    if not isinstance(ref, str) or not ref.startswith("./"):
        return ""
    path = posixpath.normpath(ref)
    return "" if path.startswith("..") or path.startswith("/") else path


class TomlEncodeError(Exception):
    pass


_TOML_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _json_text(value: Dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _toml_key(key: str) -> str:
    return key if _TOML_BARE_KEY.match(key) else json.dumps(key, ensure_ascii=False).replace("\x7f", "\\u007f")


def _toml_inline(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, list):
        return "[" + ", ".join(_toml_inline(item) for item in value) + "]"
    if isinstance(value, dict):
        items = ", ".join(f"{_toml_key(str(k))} = {_toml_inline(v)}" for k, v in value.items())
        return "{" + items + "}"
    raise TomlEncodeError(f"unsupported TOML value type: {type(value).__name__}")


def _emit_toml_table(lines: List[str], prefix: Tuple[str, ...], table: Dict[str, Any], *, emit_header: bool = True) -> None:
    scalars: List[Tuple[str, Any]] = []
    subtables: List[Tuple[str, Dict[str, Any]]] = []
    arrays_of_tables: List[Tuple[str, List[Dict[str, Any]]]] = []
    for key, val in table.items():
        if isinstance(val, dict) and val:
            subtables.append((key, val))
        elif isinstance(val, list) and val and all(isinstance(item, dict) for item in val):
            arrays_of_tables.append((key, val))
        else:
            scalars.append((key, val))
    if emit_header and prefix and (scalars or (not subtables and not arrays_of_tables)):
        if lines:
            lines.append("")
        lines.append("[" + ".".join(_toml_key(p) for p in prefix) + "]")
    for key, val in scalars:
        lines.append(f"{_toml_key(key)} = {_toml_inline(val)}")
    for key, sub in subtables:
        _emit_toml_table(lines, (*prefix, key), sub)
    for key, items in arrays_of_tables:
        path = (*prefix, key)
        header = "[[" + ".".join(_toml_key(p) for p in path) + "]]"
        for item in items:
            if lines:
                lines.append("")
            lines.append(header)
            _emit_toml_table(lines, path, item, emit_header=False)


def _toml_text(value: Dict[str, Any]) -> bytes:
    lines: List[str] = []
    _emit_toml_table(lines, (), value)
    text = ("\n".join(lines) + "\n") if lines else ""
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise TomlEncodeError("TOML serialization produced invalid TOML") from exc
    if parsed != value:
        raise TomlEncodeError("TOML serialization round-trip mismatch")
    return text.encode("utf-8")


def _check_v2_cplug_files(folder: Path, paths: List[str], prepared: publish_prepare.Prepared) -> None:
    declared_binary = install_gates._v2_declared_binary(folder)
    preview = install_gates._declared_preview(folder)
    view_files = install_gates._declared_view_files(folder)

    def _preview_err(_path: Path, rel: str) -> Optional[str]:
        try:
            read_preview(folder, rel)
        except PreviewError as exc:
            return str(exc)
        return None

    _kept, errors = validate_v2_folder_files(
        folder,
        skip_dirs=DEV_SKIP_DIRS,
        skip_root_dirs=frozenset({"tests"}),
        ignore_junk=True,
        allowed_suffixes=install_gates.V2_ALLOWED_SUFFIXES,
        allow_shell_exec=True,
        declared_binary=declared_binary,
        preview=preview,
        view_files=view_files,
        check_exec=True,
        check_magic=True,
        preview_checker=_preview_err,
        stop_on_first=True,
    )
    if errors:
        code, rel, detail = errors[0]
        refusal_code = install_gates.TOO_LARGE if code == "cplug_too_large" else install_gates.NOT_SAFE
        _refuse(prepared, refusal_code, detail, rel or None)


def _check_cplug(folder: Path, paths: List[str], read: Dict[str, bytes], prepared: publish_prepare.Prepared, handle: str, version: str = "") -> None:
    clash = sorted(p for p in paths if p.lower() in CPLUG_OTHER_KIND_MANIFESTS)
    if clash:
        _refuse(prepared, rules.SUBMISSION_INVALID, f"a plugin may not also carry another kind's manifest: {', '.join(clash)}", clash[0])
    if not has_v2_manifest(folder):
        _refuse(prepared, rules.SUBMISSION_INVALID, "a plugin must carry carnivore.toml or schema = 2 carnivore.json", None)
        return
    _check_v2_cplug_files(folder, paths, prepared)
    try:
        raw_v2, fname = load_raw_v2(folder)
    except (ManifestV2Error, OSError, ValueError) as exc:
        _refuse(prepared, rules.SUBMISSION_INVALID, str(exc), None)
        return
    try:
        api_contract.require_served(raw_v2)
    except api_contract.ApiVersionUnsupported as exc:
        _refuse(prepared, install_gates.API_VERSION_UNSUPPORTED, str(exc), fname)
        return
    try:
        v2_input = dict(raw_v2)
        if v2_input.get("tier") == TIER_LOCAL:
            v2_input.update({"tier": TIER_CATALOG, "default_enabled": False})
        v2 = parse_manifest_v2(v2_input, tier=TIER_CATALOG, allow_tier_override=False)
    except (ManifestV2Error, OSError, ValueError) as exc:
        _refuse(prepared, rules.SUBMISSION_INVALID, str(exc), fname)
        return
    if not handle:
        _refuse(prepared, rules.SUBMISSION_INVALID, "claim a publisher handle before publishing a plugin", None)
    if version and v2.version != version:
        _refuse(prepared, rules.SUBMISSION_INVALID,
                f"{fname} must carry version {version}, the version you are publishing", fname)
        return
    if not CPLUG_ID_PATTERN.match(v2.id):
        _refuse(prepared, rules.SUBMISSION_INVALID,
                f"the plugin id must match {CPLUG_ID_PATTERN.pattern} (lowercase letters and digits, no hyphen)", fname)
        return
    if v2.id in CPLUG_RESERVED_IDS:
        _refuse(prepared, rules.SUBMISSION_INVALID, "that plugin id is reserved", fname)
    try:
        validate_v2_files(folder, v2, v2.id)
    except SidecarManifestError as exc:
        _refuse(prepared, rules.SUBMISSION_INVALID, str(exc), fname)
    prepared.name = v2.id
    if fname == CPLUG_SIDECAR and CPLUG_SIDECAR in read:
        normalized = dict(raw_v2)
        normalized.update({"tier": TIER_CATALOG, "default_enabled": False})
        body = _json_text(normalized)
        prepared.total_bytes += len(body) - len(read[CPLUG_SIDECAR])
        prepared.members = [(p, body if p == CPLUG_SIDECAR else c) for p, c in prepared.members]
    elif fname == TOML_FILE and TOML_FILE in read and raw_v2.get("tier") == TIER_LOCAL:
        normalized = dict(raw_v2)
        normalized.update({"tier": TIER_CATALOG, "default_enabled": False})
        try:
            body = _toml_text(normalized)
        except TomlEncodeError as exc:
            _refuse(prepared, rules.SUBMISSION_INVALID, str(exc), fname)
            return
        prepared.total_bytes += len(body) - len(read[TOML_FILE])
        prepared.members = [(p, body if p == TOML_FILE else c) for p, c in prepared.members]
    if prepared.total_bytes > install_gates.MAX_TOTAL_BYTES:
        _refuse(prepared, rules.BODY_TOO_LARGE, f"a plugin may total at most {install_gates.MAX_TOTAL_BYTES // 1024} KiB", None)


def _json_object(raw: bytes) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def prepare_kind(kind: str, folder_path: str, version: str, handle: str = "") -> publish_prepare.Prepared:
    if kind not in _CAPS:
        raise ValueError(f"kind {kind!r} is not publishable from here")
    if not folder_path or not os.path.isdir(folder_path):
        raise submission_preview.FolderUnreadable("that folder is not readable")
    folder = Path(os.path.realpath(folder_path))
    prepared = publish_prepare.Prepared(name=folder.name, version=version, kind=kind)
    paths = _walk_v2(folder) if (kind == KIND_CPLUG and has_v2_manifest(folder)) else _walk(folder)
    if kind == KIND_MOD:
        paths = [p for p in paths if not p.startswith(_MOD_GENERATED_DIR)]
    read = _read_all(folder, paths, prepared, kind)
    if kind == KIND_THEME:
        _check_theme(paths, read, prepared)
    elif kind == KIND_MOD:
        _check_mod(paths, read, prepared)
    elif kind == KIND_CPLUG:
        _check_cplug(folder, paths, read, prepared, handle, version)
    else:
        _check_plugin(folder, paths, read, prepared)
    prepared.members.sort()
    prepared.script_files = rules.detect_script_files(
        [p for p, _ in prepared.members], dict(prepared.members)
    )
    if prepared.script_files:
        prepared.warnings.append("contains_scripts")
    prepared.digest = publish_prepare.digest_of(prepared.name, version, prepared.members)
    return prepared


def own_theme_locations(user_root: Optional[Path], installed_names: set) -> List[Dict[str, Any]]:
    if user_root is None or not user_root.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for child in sorted(user_root.iterdir(), key=lambda p: p.name.lower()):
        if child.name.startswith(".") or child.name in installed_names or not child.is_dir() or child.is_symlink():
            continue
        if not (child / THEME_MANIFEST).is_file():
            continue
        out.append({
            "location_id": f"theme:{child.name}", "kind": KIND_THEME, "name": child.name,
            "harness": "", "scope": "personal", "path": str(child), "description": "",
            "description_tokens_est": 0, "is_symlink": False, "read_only": False,
            "plugin": None, "managed": None,
        })
    return out


def own_cplug_locations(sideloaded: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for name, info in sorted(sideloaded.items()):
        source = info.get("source")
        path = Path(source) if isinstance(source, str) and source else None
        if path is None or not path.is_absolute() or path.is_symlink() or not path.is_dir():
            continue
        out.append({
            "location_id": f"cplug:{name}", "kind": KIND_CPLUG, "name": name,
            "harness": "", "scope": "personal", "path": str(path), "description": "",
            "description_tokens_est": 0, "is_symlink": False, "read_only": False,
            "plugin": None, "managed": None,
        })
    return out

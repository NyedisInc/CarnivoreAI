
from __future__ import annotations

import json
import os
import posixpath
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core import message_model_secrets
from src.core.catalog import publish_prepare, submission_preview
from src.core.catalog import submission_rules as rules
from src.core.skills.plugin_safe_subset import CODE_MANIFEST_KEYS, mcp_problems, plugin_declares_nonmcp_code
from src.cplugs.host import install_gates
from src.cplugs.sdk.manifest import ID_PATTERN as CPLUG_ID_PATTERN, RESERVED_IDS as CPLUG_RESERVED_IDS

logger = structlog.get_logger()

KIND_THEME = "theme"
KIND_PLUGIN = "plugin"
KIND_MOD = "mod"
KIND_CPLUG = "cplug"
CPLUG_MANIFEST = "cplug.json"
CPLUG_SIDECAR = "carnivore.json"
CPLUG_OTHER_KIND_MANIFESTS = frozenset({"skill.md", "theme.json", ".claude-plugin/plugin.json", "hooks/hooks.json"})
HOOKS_MANIFEST = "hooks/hooks.json"
THEME_MANIFEST = "theme.json"
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"

_THEME_SCRIPT_EXT = (".js", ".mjs", ".cjs", ".svg", ".html", ".htm", ".css")
_THEME_IMAGE_EXT = (".webp", ".png", ".jpg")
_THEME_KEYS = frozenset(
    {"id", "name", "description", "author", "version", "cssVars", "xterm", "background"}
)
_PLUGIN_FORBIDDEN_SEGMENTS = frozenset({"hooks", "bin", "monitors", "scripts", ".claude", "node_modules"})
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
_MOD_MANIFEST_KEYS = frozenset(
    {"name", "version", "description", "author", "homepage", "repository", "license", "keywords", "types"}
)
_MOD_SOURCE_EXT = (".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs", ".jsx")
_MOD_FILE_EXT = _MOD_SOURCE_EXT + (".json", ".md")
_MOD_MAX_LISTED = 10


def _walk(folder: Path) -> List[str]:
    found: List[str] = []
    for root, dirs, files in os.walk(folder, followlinks=False):
        rel = Path(root).relative_to(folder)
        found.extend((rel / name).as_posix() for name in files + [d for d in dirs if os.path.islink(Path(root) / d)])
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
        found = sorted({f.detector for f in message_model_secrets.scan_text(content.decode("utf-8", errors="replace"))})
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
        low = path.lower()
        if "/" in path or path.startswith("."):
            _refuse(prepared, rules.SUBMISSION_INVALID, "a theme holds files at its root only, none hidden", path)
        elif low.endswith(_THEME_SCRIPT_EXT):
            _refuse(prepared, rules.SCRIPTS_NOT_SUPPORTED, "a theme is data: no script, stylesheet, svg or html", path)
        elif path != THEME_MANIFEST and not low.endswith(_THEME_IMAGE_EXT):
            _refuse(prepared, rules.SUBMISSION_INVALID, "only theme.json and webp, png or jpg images are allowed", path)
    raw = read.get(THEME_MANIFEST)
    if raw is None:
        _refuse(prepared, rules.SUBMISSION_INVALID, "the folder carries no theme.json", None)
        return
    manifest = _json_object(raw)
    if manifest is None:
        _refuse(prepared, rules.SUBMISSION_INVALID, "theme.json is not a json object", THEME_MANIFEST)
        return
    for key in sorted(set(manifest) - _THEME_KEYS):
        code = rules.SCRIPTS_NOT_SUPPORTED if key == "effects" else rules.SUBMISSION_INVALID
        _refuse(prepared, code, f"theme.json may not carry the key {key!r}", THEME_MANIFEST)


def _plugin_path_allowed(path: str) -> bool:
    parts = path.split("/")
    if path == PLUGIN_MANIFEST or path == ".mcp.json":
        return True
    if any(p.lower() in _PLUGIN_FORBIDDEN_SEGMENTS for p in parts) or _PLUGIN_FORBIDDEN_NAMES.match(parts[-1]):
        return False
    if len(parts) == 1:
        return bool(_PLUGIN_ROOT_DOC.match(path))
    lower = path.lower()
    if parts[0] in ("commands", "agents"):
        return lower.endswith(".md")
    if parts[0] == "skills" and len(parts) >= 3:
        return lower.endswith(_PLUGIN_TEXT_EXT)
    return False


def _check_plugin(folder: Path, paths: List[str], read: Dict[str, bytes], prepared: publish_prepare.Prepared) -> None:
    named = False
    for path in paths:
        if not _plugin_path_allowed(path):
            _refuse(prepared, "plugin_not_safe", "a plugin may carry only its manifest, markdown commands, agents, skills and a readme", path)
            named = True
    raw = read.get(PLUGIN_MANIFEST)
    manifest = _json_object(raw) if raw is not None else None
    if manifest is None:
        _refuse(prepared, rules.SUBMISSION_INVALID, "the folder carries no readable .claude-plugin/plugin.json", None)
        return
    for key in CODE_MANIFEST_KEYS:
        if key != "mcpServers" and key in manifest:
            _refuse(prepared, "plugin_not_safe", f"plugin.json may not carry {key!r}", PLUGIN_MANIFEST)
            named = True
    for problem in mcp_problems(manifest, read.get(".mcp.json")):
        _refuse(prepared, "plugin_not_safe", f"an mcp server declaration is malformed: {problem}", PLUGIN_MANIFEST)
        named = True
    if not named and plugin_declares_nonmcp_code(manifest, folder):
        _refuse(prepared, "plugin_not_safe", "a file carries a shell line or tool-granting front matter", PLUGIN_MANIFEST)
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
        elif not path.lower().endswith(_MOD_FILE_EXT):
            problems.append(f"{path} (extension not allowed)")
        elif path in read and read[path].lstrip(b"\xef\xbb\xbf").startswith(b"#!"):
            problems.append(f"{path} (shebang)")
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


def _json_text(value: Dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _check_cplug(folder: Path, paths: List[str], read: Dict[str, bytes], prepared: publish_prepare.Prepared, handle: str, version: str = "") -> None:
    try:
        install_gates.check_files(folder)
    except install_gates.CplugGateRefusal as exc:
        _refuse(prepared, exc.code, exc.detail, None)
    clash = sorted(p for p in paths if p.lower() in CPLUG_OTHER_KIND_MANIFESTS)
    if clash:
        _refuse(prepared, rules.SUBMISSION_INVALID, f"a plugin may not also carry another kind's manifest: {', '.join(clash)}", clash[0])
    manifest = _json_object(read[CPLUG_MANIFEST]) if CPLUG_MANIFEST in read else None
    sidecar = _json_object(read[CPLUG_SIDECAR]) if CPLUG_SIDECAR in read else None
    if manifest is None:
        _refuse(prepared, rules.SUBMISSION_INVALID, "the folder carries no readable cplug.json", None)
    if sidecar is None:
        _refuse(prepared, rules.SUBMISSION_INVALID, "the folder carries no readable carnivore.json", None)
    if not handle:
        _refuse(prepared, rules.SUBMISSION_INVALID, "claim a publisher handle before publishing a plugin", None)
    if manifest is None or sidecar is None:
        return
    if version and (manifest.get("version") != version or sidecar.get("version") != version):
        _refuse(prepared, rules.SUBMISSION_INVALID,
                f"cplug.json and carnivore.json must both carry version {version}, the version you are publishing", CPLUG_MANIFEST)
        return
    name = manifest.get("id")
    if not isinstance(name, str) or not CPLUG_ID_PATTERN.match(name):
        _refuse(prepared, rules.SUBMISSION_INVALID,
                f"the plugin id must match {CPLUG_ID_PATTERN.pattern} (lowercase letters and digits, no hyphen)", CPLUG_MANIFEST)
        return
    if name in CPLUG_RESERVED_IDS:
        _refuse(prepared, rules.SUBMISSION_INVALID, "that plugin id is reserved", CPLUG_MANIFEST)
    entry = manifest.get("entry")
    if not isinstance(entry, str) or entry not in read or not entry.endswith(".py"):
        _refuse(prepared, rules.SUBMISSION_INVALID, "entry must name a .py file in the folder", CPLUG_MANIFEST)
    runtime = sidecar.get("runtime")
    if not isinstance(runtime, dict):
        _refuse(prepared, rules.SUBMISSION_INVALID, "carnivore.json needs a runtime object", CPLUG_SIDECAR)
    elif runtime.get("kind") == "process" and not isinstance(sidecar.get("network_hosts"), list):
        _refuse(prepared, rules.SUBMISSION_INVALID,
                "carnivore.json needs network_hosts for a process runtime (an empty list is allowed)", CPLUG_SIDECAR)
    if not isinstance(sidecar.get("data"), list):
        _refuse(prepared, rules.SUBMISSION_INVALID, "carnivore.json needs a data list (an empty list is allowed)", CPLUG_SIDECAR)
    prepared.name = name
    manifest["default_enabled"] = False
    sidecar.update({"kind": "cplug", "id": f"{handle}/{name}", "tier": "catalog", "default_enabled": False})
    for path, doc in ((CPLUG_MANIFEST, manifest), (CPLUG_SIDECAR, sidecar)):
        body = _json_text(doc)
        prepared.total_bytes += len(body) - len(read[path])
        prepared.members = [(p, body if p == path else c) for p, c in prepared.members]


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
    paths = _walk(folder)
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

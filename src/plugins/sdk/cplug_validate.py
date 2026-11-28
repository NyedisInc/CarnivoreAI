
from __future__ import annotations

import io
import json
import os
import posixpath
import re
import stat
import struct
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple

if __package__:
    from . import api_contract, manifest_v2
    from ._manifest_v2_sections import ManifestV2Error, _parse_views
    from .permission_registry import TIER_CATALOG
else:
    import api_contract  # type: ignore[no-redef]
    import manifest_v2  # type: ignore[no-redef]
    from _manifest_v2_sections import ManifestV2Error, _parse_views  # type: ignore[no-redef]
    from permission_registry import TIER_CATALOG  # type: ignore[no-redef]

TOML_FILE = manifest_v2.TOML_FILE
JSON_FILE = manifest_v2.JSON_FILE
LEGACY_MANIFEST = "cplug.json"
OTHER_KIND_MANIFESTS = frozenset({"skill.md", "theme.json", ".claude-plugin/plugin.json", "hooks/hooks.json"})

MAX_MANIFEST_BYTES = 64 * 1024
MAX_MEMBERS = 500
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 3 * 1024 * 1024
MAX_LISTED = 10

ALLOWED_SUFFIXES = frozenset({".py", ".json", ".toml", ".md", ".txt"})
V2_ALLOWED_SUFFIXES = ALLOWED_SUFFIXES | frozenset(
    {".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".sh", ".bash", ".yaml", ".yml"}
)
VIEW_SUFFIXES = frozenset({".html", ".css", ".js", ".svg", ".png", ".woff2"})
PREVIEW_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
SOURCE_SHEBANG_SUFFIXES = frozenset({".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".sh", ".bash"})
NON_SOURCE_TEXT_SUFFIXES = frozenset({".json", ".toml", ".md", ".txt", ".html", ".css", ".svg", ".yaml", ".yml"})
TEXT_SUFFIXES = SOURCE_SHEBANG_SUFFIXES | NON_SOURCE_TEXT_SUFFIXES

NATIVE_MAGIC = (
    b"\x7fELF",
    b"MZ",
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
)
DECLARED_BIN_SUFFIXES = frozenset({"", ".bin"})
_NON_BIN_PREFIXES = ("views/", "harnesses/", ".claude-plugin/")
_NON_BIN_FILES = frozenset({"views", TOML_FILE, JSON_FILE, LEGACY_MANIFEST})
_INTERPRETERS = frozenset({"python", "python3", "uv", "node", "bun", "bash", "sh"})

PREVIEW_MAX_BYTES = 512 * 1024
PREVIEW_MIN_WIDTH, PREVIEW_MIN_HEIGHT = 1200, 500
PREVIEW_MAX_SIDE = 8192
PREVIEW_MAX_PIXELS = 16_000_000
PREVIEW_RATIO_MIN, PREVIEW_RATIO_MAX = 1.5, 3.0

ID_PATTERN = manifest_v2.ID_PATTERN
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

_V1_VIEW_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_V1_VIEW_FILE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*$")
_V1_VIEW_UNITS = {"small": (1, 1), "wide": (2, 1), "tall": (2, 4), "medium": (4, 4), "large": (6, 5), "full": (12, 5)}

RESERVED_IDS: FrozenSet[str] = manifest_v2.RESERVED_IDS | frozenset({
    "state", "safe-mode", "r", "restart", "kill", "profiles",
    "archive", "stats", "budget", "github", "slack", "discord", "telegram", "sns", "unread", "share", "huddle",
    "deepsearch", "backup", "summarize", "save", "ntfy", "pushover", "n8n", "homeassistant", "spotify", "addons",
    "nudge", "publicboard",
    "argent", "crate", "devwidgetlab", "flow", "reviewboard", "sessionchat", "taskmanager", "timemachine", "tmdevtools",
})


class CplugValidationError(ValueError):

    def __init__(self, status: int, code: str, detail: str, path: Optional[str] = None) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.path = path


def is_allowed_declared_binary_path(cmd0: str, *, preview: str = "") -> str:
    raw = cmd0.strip()
    if not raw or raw.startswith("/") or "\\" in raw:
        return ""
    p = PurePosixPath(raw)
    if ".." in p.parts:
        return ""
    exe = p.name.lower()
    if exe in _INTERPRETERS or exe.startswith("python"):
        return ""
    rel = p.as_posix()
    norm_preview = PurePosixPath(preview.strip()).as_posix() if preview.strip() else ""
    if not rel or rel == "." or rel in _NON_BIN_FILES or rel.startswith(_NON_BIN_PREFIXES) or (norm_preview and rel == norm_preview):
        return ""
    if p.suffix.lower() not in DECLARED_BIN_SUFFIXES:
        return ""
    return rel


def v2_declared_binary_from_raw(raw: Mapping[str, Any]) -> str:
    run = raw.get("run")
    if not isinstance(run, Mapping):
        return ""
    cmd = run.get("cmd")
    if not isinstance(cmd, list) or not cmd or not isinstance(cmd[0], str):
        return ""
    preview = raw.get("preview") if isinstance(raw.get("preview"), str) else ""
    return is_allowed_declared_binary_path(cmd[0], preview=preview)


def v2_declared_view_files_from_raw(raw: Mapping[str, Any], source: str = TOML_FILE) -> Optional[FrozenSet[str]]:
    ui = raw.get("ui")
    if ui is None:
        return frozenset()
    if not isinstance(ui, Mapping):
        return None
    try:
        views = _parse_views(ui.get("views"), source)
    except ManifestV2Error:
        return None
    return frozenset(f"views/{v['name']}/{p}" for v in views for p in v["files"])


def check_preview_bytes(raw: bytes) -> Optional[str]:
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return "the preview is empty"
    data = bytes(raw)
    if len(data) > PREVIEW_MAX_BYTES:
        return "the preview is over 512 KiB"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        if len(data) < 24 or data[12:16] != b"IHDR":
            return "the png header is damaged"
        w, h = struct.unpack(">II", data[16:24])
    elif data[:3] == b"\xff\xd8\xff":
        i = 2
        w = h = 0
        while i + 9 < len(data):
            if data[i] != 0xFF:
                return "the jpeg is damaged"
            marker = data[i + 1]
            if marker == 0xFF:
                i += 1
                continue
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            (length,) = struct.unpack(">H", data[i + 2:i + 4])
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                break
            i += 2 + length
        if not w or not h:
            return "the jpeg has no size header"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if len(data) < 30:
            return "the webp header is damaged"
        fourcc, body = data[12:16], data[20:]
        if fourcc == b"VP8 " and body[3:6] == b"\x9d\x01\x2a":
            w, h = struct.unpack("<HH", body[6:10])
            w, h = w & 0x3FFF, h & 0x3FFF
        elif fourcc == b"VP8L" and body[:1] == b"\x2f":
            bits = int.from_bytes(body[1:5], "little")
            w, h = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        elif fourcc == b"VP8X":
            w, h = int.from_bytes(body[4:7], "little") + 1, int.from_bytes(body[7:10], "little") + 1
        else:
            return "the webp is not a still image"
    else:
        return "the preview must be a png, jpeg or webp"
    if w < PREVIEW_MIN_WIDTH or h < PREVIEW_MIN_HEIGHT or w > PREVIEW_MAX_SIDE or h > PREVIEW_MAX_SIDE or w * h > PREVIEW_MAX_PIXELS:
        return (
            f"the preview is {w}x{h}; it must be at least {PREVIEW_MIN_WIDTH}x{PREVIEW_MIN_HEIGHT} "
            f"and at most {PREVIEW_MAX_PIXELS // 1_000_000} megapixels"
        )
    if not PREVIEW_RATIO_MIN <= w / h <= PREVIEW_RATIO_MAX:
        return f"the preview is {w}x{h}; its width must be 1.5 to 3 times its height"
    return None


def load_raw_v2_members(members: Mapping[str, bytes]) -> Tuple[Dict[str, Any], str]:
    has_toml = TOML_FILE in members
    has_json = JSON_FILE in members
    has_legacy = LEGACY_MANIFEST in members
    if (has_toml or has_json) and has_legacy:
        raise CplugValidationError(400, "cplug_invalid", "a plugin cannot carry both a v2 manifest and legacy cplug.json")
    if has_toml and has_json:
        raise CplugValidationError(400, "cplug_invalid", "a plugin cannot carry both carnivore.toml and carnivore.json")
    if has_toml:
        filename = TOML_FILE
        raw_bytes = members[TOML_FILE]
    elif has_json:
        filename = JSON_FILE
        raw_bytes = members[JSON_FILE]
    elif has_legacy:
        raise CplugValidationError(400, "cplug_invalid", "a plugin must carry carnivore.toml or schema = 2 carnivore.json")
    else:
        raise CplugValidationError(400, "cplug_invalid", "the folder carries no carnivore.toml or carnivore.json")

    if len(raw_bytes) > MAX_MANIFEST_BYTES:
        raise CplugValidationError(400, "cplug_invalid", f"{filename} is larger than 64 KiB", filename)
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CplugValidationError(400, "cplug_invalid", f"{filename} is not utf-8", filename) from exc
    try:
        parsed = tomllib.loads(text) if filename == TOML_FILE else json.loads(text)
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        kind_word = "toml" if filename == TOML_FILE else "json"
        raise CplugValidationError(400, "cplug_invalid", f"{filename} is not valid {kind_word}", filename) from exc
    if not isinstance(parsed, dict):
        raise CplugValidationError(400, "cplug_invalid", f"{filename} must be an object/table", filename)
    if type(parsed.get("schema")) is not int or parsed.get("schema") != 2:
        raise CplugValidationError(400, "cplug_invalid", f"{filename} must declare schema = 2", filename)
    return parsed, filename


def _default_content_check(path: str, data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "not utf-8"
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("#!"):
        return "shebang"
    return ""


def _v1_declared_view_files(manifest: dict) -> Optional[FrozenSet[str]]:
    views = manifest.get("views", [])
    if views is None:
        return frozenset()
    if not isinstance(views, list) or len(views) > 8:
        return None
    paths: set[str] = set()
    names: set[str] = set()
    for view in views:
        if not isinstance(view, dict) or not {"name", "surfaces", "files"} <= view.keys() <= {"name", "surfaces", "files", "fits"}:
            return None
        vname, surfaces, files = view["name"], view["surfaces"], view["files"]
        if not isinstance(vname, str) or not _V1_VIEW_NAME.fullmatch(vname) or vname in names:
            return None
        if not isinstance(surfaces, list) or not surfaces or any(not isinstance(s, str) or s not in {"panel", "overlay"} for s in surfaces) or len(set(surfaces)) != len(surfaces):
            return None
        fits = view.get("fits")
        if fits is not None:
            if not isinstance(fits, dict) or not set(fits) <= {"sizes", "min", "anySize"} or "sizes" not in fits:
                return None
            sizes = fits["sizes"]
            if not isinstance(sizes, list) or not sizes or any(not isinstance(s, str) or s not in _V1_VIEW_UNITS for s in sizes) or len(set(sizes)) != len(sizes):
                return None
            floor = (min(_V1_VIEW_UNITS[s][0] for s in sizes), min(_V1_VIEW_UNITS[s][1] for s in sizes))
            low = fits.get("min", {"w": floor[0], "h": floor[1]})
            if not isinstance(low, dict) or set(low) != {"w", "h"}:
                return None
            if any(not isinstance(low[k], int) or isinstance(low[k], bool) or not 1 <= low[k] <= 12 for k in ("w", "h")):
                return None
            if low["w"] > floor[0] or low["h"] > floor[1] or not isinstance(fits.get("anySize", False), bool):
                return None
        if not isinstance(files, list) or not 1 <= len(files) <= 64 or any(not isinstance(f, str) for f in files) or len(set(files)) != len(files) or "index.html" not in files:
            return None
        names.add(vname)
        for p in files:
            if not isinstance(p, str) or len(p) > 120 or not _V1_VIEW_FILE.fullmatch(p) or PurePosixPath(p).suffix not in VIEW_SUFFIXES:
                return None
            paths.add(f"views/{vname}/{p}")
    return frozenset(paths)


def _validate_legacy_v1_members(
    name: str,
    members: Mapping[str, bytes],
    *,
    handle: str,
    version: str,
    content_checker: Callable[[str, bytes], str],
    preview_checker: Callable[[bytes], Optional[str]],
) -> Tuple[Dict[str, Any], str]:
    def _json_obj(path: str) -> dict:
        raw = members.get(path)
        if raw is None:
            raise CplugValidationError(400, "cplug_invalid", f"the folder carries no {path}", path)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise CplugValidationError(400, "cplug_invalid", f"{path} is larger than 64 KiB", path)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise CplugValidationError(400, "cplug_invalid", f"{path} is not utf-8 json", path) from exc
        if not isinstance(parsed, dict):
            raise CplugValidationError(400, "cplug_invalid", f"{path} must be a json object", path)
        return parsed

    manifest = _json_obj(LEGACY_MANIFEST)
    sidecar = _json_obj(JSON_FILE)
    problems: List[str] = []
    view_files = _v1_declared_view_files(manifest)
    if view_files is None:
        problems.append(f"{LEGACY_MANIFEST} (invalid views declaration)")
        view_files = frozenset()
    preview = manifest.get("preview")
    if "preview" in manifest and (not isinstance(preview, str) or preview not in members):
        problems.append(f"{LEGACY_MANIFEST} (preview must name an image file in the folder)")
        preview = None
    total = 0
    for path, data in members.items():
        total += len(data)
        suffix = PurePosixPath(path).suffix.lower()
        parts = path.lower().split("/")
        if data.startswith(NATIVE_MAGIC) or zipfile.is_zipfile(io.BytesIO(data)):
            problems.append(f"{path} (executable or archive)")
            continue
        if path == preview:
            if suffix not in PREVIEW_SUFFIXES:
                problems.append(f"{path} (the preview must be a .png, .jpg, .jpeg or .webp file)")
            else:
                reason = preview_checker(data)
                if reason:
                    problems.append(f"{path} ({reason})")
        elif suffix not in ALLOWED_SUFFIXES and not (path in view_files and suffix in VIEW_SUFFIXES):
            problems.append(f"{path} (extension not allowed)")
        elif "node_modules" in parts or parts[-1] == "package.json":
            problems.append(f"{path} (path not allowed)")
        elif len(data) > MAX_FILE_BYTES:
            problems.append(f"{path} (larger than {MAX_FILE_BYTES // 1024} KiB)")
        elif path in view_files and suffix in {".png", ".woff2"} and not data.startswith(
            b"\x89PNG\r\n\x1a\n" if suffix == ".png" else b"wOF2"
        ):
            problems.append(f"{path} (not a plain {suffix[1:]} asset)")
        elif suffix in TEXT_SUFFIXES:
            if suffix in SOURCE_SHEBANG_SUFFIXES:
                try:
                    data.decode("utf-8")
                    reason = ""
                except UnicodeDecodeError:
                    reason = "not utf-8"
            else:
                reason = content_checker(path, data)
            if reason:
                problems.append(f"{path} ({reason})")
    if total > MAX_TOTAL_BYTES:
        problems.append("the folder (larger than 3 MiB)")
    if manifest.get("id") != name:
        problems.append(f"{LEGACY_MANIFEST} (id is not the folder name)")
    entry = manifest.get("entry")
    target = posixpath.normpath(entry) if isinstance(entry, str) and entry else ""
    if not target or target.startswith(("..", "/")) or target not in members or not target.endswith(".py"):
        problems.append(f"{LEGACY_MANIFEST} (entry must name a .py file in the folder)")
    if manifest.get("default_enabled") is not False:
        problems.append(f"{LEGACY_MANIFEST} (default_enabled must be false)")
    declared = manifest.get("version")
    if not isinstance(declared, str) or not SEMVER.match(declared) or sidecar.get("version") != declared:
        problems.append(f"{JSON_FILE} (version must be semver and equal the one in {LEGACY_MANIFEST})")
    if version and version != declared:
        problems.append(f"{LEGACY_MANIFEST} (version {declared!r} must equal the submitted version {version})")
    if sidecar.get("kind") != "cplug" or sidecar.get("id") != f"{handle}/{name}":
        problems.append(f"{JSON_FILE} (kind must be cplug and id {handle}/{name})")
    if sidecar.get("tier") != "catalog":
        problems.append(f"{JSON_FILE} (tier must be catalog)")
    if sidecar.get("default_enabled") is not False:
        problems.append(f"{JSON_FILE} (default_enabled must be false)")
    if problems:
        more = f"; and {len(problems) - MAX_LISTED} more" if len(problems) > MAX_LISTED else ""
        raise CplugValidationError(409, "cplug_not_safe", f"a plugin may not carry: {'; '.join(problems[:MAX_LISTED])}{more}")
    return manifest, members[LEGACY_MANIFEST].decode("utf-8")


def _check_v2_member_references(
    v2: manifest_v2.ManifestV2,
    manifest_filename: str,
    members: Mapping[str, bytes],
    problems: List[str],
) -> None:
    if not v2.tier0 and v2.run_cmd:
        cmd0 = v2.run_cmd[0]
        exe = PurePosixPath(cmd0).name.lower()
        if not cmd0.startswith("/") and (cmd0.startswith("./") or "/" in cmd0 or exe not in _INTERPRETERS):
            norm_bin = posixpath.normpath(cmd0)
            if norm_bin.startswith(("..", "/")) or norm_bin not in members:
                problems.append(f"{manifest_filename} (executable {cmd0!r} is not a file in the folder)")
        if v2.entry and v2.entry != cmd0:
            norm_entry = posixpath.normpath(v2.entry)
            if norm_entry.startswith(("..", "/")) or norm_entry not in members:
                problems.append(f"{manifest_filename} (entry {v2.entry!r} is not a file in the folder)")
    for ui_key in ("widget", "sidebar_tab"):
        decl = v2.ui_meta.get(ui_key) if isinstance(v2.ui_meta, Mapping) else None
        if isinstance(decl, Mapping) and "ui_file" in decl:
            ui_rel = posixpath.normpath(str(decl["ui_file"]))
            if ui_rel.startswith(("..", "/")) or ui_rel not in members:
                problems.append(f"{manifest_filename} ({ui_key}.ui_file {decl['ui_file']!r} is missing)")
    for rel in v2.harnesses:
        h_rel = posixpath.normpath(rel)
        if h_rel.startswith(("..", "/")) or h_rel not in members:
            problems.append(f"{manifest_filename} (harness {rel!r} is missing)")


def validate_cplug_members(
    name: str,
    members: Mapping[str, bytes],
    *,
    handle: str = "",
    version: str = "",
    content_checker: Optional[Callable[[str, bytes], str]] = None,
    preview_checker: Optional[Callable[[bytes], Optional[str]]] = None,
    allow_v1: bool = False,
    check_reserved: bool = True,
    tier: str = TIER_CATALOG,
    expected_tier: Optional[str] = TIER_CATALOG,
    allow_tier_override: bool = False,
) -> Tuple[Any, str]:
    if not isinstance(name, str) or not ID_PATTERN.match(name):
        raise CplugValidationError(400, "cplug_invalid", "name must match " + ID_PATTERN.pattern)
    if check_reserved and name in RESERVED_IDS:
        raise CplugValidationError(409, "name_reserved", "that name is reserved for the app")
    if len(members) > MAX_MEMBERS:
        raise CplugValidationError(400, "cplug_invalid", f"a plugin may carry at most {MAX_MEMBERS} files")
    clash = sorted(m for m in members if m.lower() in OTHER_KIND_MANIFESTS)
    if clash:
        raise CplugValidationError(400, "cplug_invalid", f"a plugin may not also carry another kind's manifest: {', '.join(clash)}")

    c_check = content_checker or _default_content_check
    p_check = preview_checker or check_preview_bytes

    if allow_v1 and TOML_FILE not in members and LEGACY_MANIFEST in members:
        return _validate_legacy_v1_members(
            name,
            members,
            handle=handle,
            version=version,
            content_checker=c_check,
            preview_checker=p_check,
        )

    raw, filename = load_raw_v2_members(members)
    try:
        api_contract.require_served(raw)
    except api_contract.ApiVersionUnsupported as exc:
        raise CplugValidationError(409, "cplug_api_version_unsupported", str(exc), filename) from exc

    problems: List[str] = []
    view_files = v2_declared_view_files_from_raw(raw, filename)
    if view_files is None:
        problems.append(f"{filename} (invalid views declaration)")
        view_files = frozenset()

    preview = raw.get("preview")
    if "preview" in raw and (not isinstance(preview, str) or preview not in members):
        problems.append(f"{filename} (preview must name an image file in the folder)")
        preview = None

    screenshots_raw = raw.get("screenshots")
    screenshot_paths: set[str] = set()
    if "screenshots" in raw:
        if not isinstance(screenshots_raw, list) or len(screenshots_raw) > 4:
            problems.append(f"{filename} (screenshots must be a list of at most 4 image files in the folder)")
        else:
            for item_s in screenshots_raw:
                if not isinstance(item_s, str) or item_s not in members:
                    problems.append(f"{filename} (screenshot {item_s!r} must name an image file in the folder)")
                else:
                    screenshot_paths.add(item_s)

    icon_file = raw.get("icon_file")
    if "icon_file" in raw and (not isinstance(icon_file, str) or icon_file not in members):
        problems.append(f"{filename} (icon_file must name a .png or .webp file in the folder)")
        icon_file = None

    declared_binary = v2_declared_binary_from_raw(raw)
    total = 0
    for path, data in members.items():
        total += len(data)
        suffix = PurePosixPath(path).suffix.lower()
        parts = path.lower().split("/")
        is_preview = path == preview
        is_screenshot = path in screenshot_paths
        is_icon = bool(icon_file and path == icon_file)
        is_declared_bin = bool(declared_binary and path == declared_binary)

        if zipfile.is_zipfile(io.BytesIO(data)) or (data.startswith(NATIVE_MAGIC) and not is_declared_bin):
            problems.append(f"{path} (executable or archive)")
            continue
        if "node_modules" in parts:
            problems.append(f"{path} (path not allowed)")
            continue
        if is_icon:
            if suffix not in {".png", ".webp"}:
                problems.append(f"{path} (icon_file must be a .png or .webp file)")
            else:
                from src.plugins.host.preview_check import PreviewError, check_icon
                try:
                    check_icon(data)
                except PreviewError as exc:
                    problems.append(f"{path} ({exc})")
            continue
        if is_preview:
            if suffix not in PREVIEW_SUFFIXES:
                problems.append(f"{path} (the preview must be a .png, .jpg, .jpeg or .webp file)")
            else:
                reason = p_check(data)
                if reason:
                    problems.append(f"{path} ({reason})")
            continue
        if is_screenshot:
            if suffix not in PREVIEW_SUFFIXES:
                problems.append(f"{path} (each screenshot must be a .png, .jpg, .jpeg or .webp file)")
            else:
                from src.plugins.host.preview_check import PreviewError, check_screenshot
                try:
                    check_screenshot(data)
                except PreviewError as exc:
                    problems.append(f"{path} ({exc})")
            continue
        if path == "views" or path.startswith("views/"):
            if path not in view_files or suffix not in VIEW_SUFFIXES:
                problems.append(f"{path} (extension not allowed)")
                continue
        elif is_declared_bin:
            pass
        elif suffix not in V2_ALLOWED_SUFFIXES:
            problems.append(f"{path} (extension not allowed)")
            continue

        if len(data) > MAX_FILE_BYTES:
            problems.append(f"{path} (larger than {MAX_FILE_BYTES // 1024} KiB)")
        elif path in view_files and suffix in {".png", ".woff2"} and not data.startswith(
            b"\x89PNG\r\n\x1a\n" if suffix == ".png" else b"wOF2"
        ):
            problems.append(f"{path} (not a plain {suffix[1:]} asset)")
        elif suffix in TEXT_SUFFIXES and not is_declared_bin:
            if suffix in SOURCE_SHEBANG_SUFFIXES:
                try:
                    data.decode("utf-8")
                    reason = ""
                except UnicodeDecodeError:
                    reason = "not utf-8"
            else:
                reason = c_check(path, data)
            if reason:
                problems.append(f"{path} ({reason})")

    if total > MAX_TOTAL_BYTES:
        problems.append("the folder (larger than 3 MiB)")

    try:
        v2 = manifest_v2.parse_manifest_v2(
            raw,
            expected_id=name,
            tier=tier,
            expected_tier=expected_tier,
            allow_tier_override=allow_tier_override,
        )
    except ManifestV2Error as exc:
        problems.append(f"{filename} ({exc})")
    else:
        if expected_tier == TIER_CATALOG and v2.default_enabled is True:
            problems.append(f"{filename} (default_enabled must not be true)")
        if version and v2.version != version:
            problems.append(f"{filename} (version {v2.version!r} must equal the submitted version {version})")
        _check_v2_member_references(v2, filename, members, problems)

    if problems:
        more = f"; and {len(problems) - MAX_LISTED} more" if len(problems) > MAX_LISTED else ""
        raise CplugValidationError(409, "cplug_not_safe", f"a plugin may not carry: {'; '.join(problems[:MAX_LISTED])}{more}")
    return v2, members[filename].decode("utf-8")


def validate_v2_folder_files(
    root: Path,
    *,
    skip_dirs: FrozenSet[str] = frozenset(),
    skip_root_dirs: FrozenSet[str] = frozenset(),
    ignore_junk: bool = False,
    allowed_suffixes: FrozenSet[str] = V2_ALLOWED_SUFFIXES,
    allow_shell_exec: bool = True,
    declared_binary: str = "",
    preview: str = "",
    icon_file: str = "",
    view_files: FrozenSet[str] = frozenset(),
    check_exec: bool = True,
    check_magic: bool = True,
    forbid_node_pkg: bool = False,
    preview_checker: Optional[Callable[[Path, str], Optional[str]]] = None,
    icon_checker: Optional[Callable[[Path, str], Optional[str]]] = None,
    stop_on_first: bool = True,
) -> Tuple[List[Path], List[Tuple[str, str, str]]]:
    kept: List[Path] = []
    errors: List[Tuple[str, str, str]] = []
    total = 0

    def _err(code: str, rel: str, detail: str) -> bool:
        errors.append((code, rel, detail))
        return stop_on_first

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        active_skip = skip_dirs | (skip_root_dirs if rel_dir == Path(".") else frozenset())
        if active_skip:
            for dname in sorted(dirnames):
                if dname not in active_skip and os.path.islink(os.path.join(dirpath, dname)):
                    if _err("cplug_not_safe", (rel_dir / dname).as_posix(), "a plugin may not contain a symbolic link"):
                        return kept, errors
            dirnames[:] = sorted(d for d in dirnames if d not in active_skip)
        else:
            dirnames.sort()
            for dname in dirnames:
                if stat.S_ISLNK(os.lstat(os.path.join(dirpath, dname)).st_mode):
                    if _err("cplug_not_safe", (rel_dir / dname).as_posix(), "a plugin may not contain a symbolic link"):
                        return kept, errors
        for fname in sorted(filenames):
            if ignore_junk and (fname == ".DS_Store" or fname.startswith("._") or fname.endswith((".pyc", ".pyo"))):
                continue
            path = Path(dirpath) / fname
            rel = path.relative_to(root).as_posix()
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode):
                if _err("cplug_not_safe", rel, "a plugin may not contain a symbolic link"):
                    return kept, errors
                continue
            if not stat.S_ISREG(info.st_mode):
                if _err("cplug_not_safe", rel, "a plugin may carry regular files only"):
                    return kept, errors
                continue
            if len(kept) >= MAX_MEMBERS:
                _err("cplug_too_large", "", f"a plugin may carry at most {MAX_MEMBERS} files")
                return kept, errors
            kept.append(path)
            suffix = path.suffix.lower()
            parts = rel.lower().split("/")
            is_preview = bool(preview and rel == preview)
            is_icon = bool(icon_file and rel == icon_file)
            is_declared_bin = bool(declared_binary and rel == declared_binary)
            if "node_modules" in parts or (forbid_node_pkg and parts[-1] == "package.json"):
                if _err("cplug_not_safe", rel, f"{rel[:120]} is not allowed"):
                    return kept, errors
                continue
            if is_preview:
                if preview_checker is not None:
                    reason = preview_checker(path, rel)
                    if reason:
                        if _err("cplug_not_safe", rel, f"{rel[:120]}: {reason}"):
                            return kept, errors
                        continue
            elif is_icon:
                if icon_checker is not None:
                    reason = icon_checker(path, rel)
                    if reason:
                        if _err("cplug_not_safe", rel, f"{rel[:120]}: {reason}"):
                            return kept, errors
                        continue
            elif rel == "views" or rel.startswith("views/"):
                if rel not in view_files or suffix not in VIEW_SUFFIXES:
                    if _err("cplug_not_safe", rel, f"{rel[:120]} is not a declared view file"):
                        return kept, errors
                    continue
            elif is_declared_bin:
                pass
            elif suffix not in allowed_suffixes:
                if _err("cplug_not_safe", rel, f"{rel[:120]} is not a file type a plugin may carry"):
                    return kept, errors
                continue
            allow_exec = is_declared_bin or (allow_shell_exec and suffix in {".sh", ".bash"})
            if check_exec and (info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)) and not allow_exec:
                if _err("cplug_not_safe", rel, f"{rel[:120]} is executable; a plugin ships plain files"):
                    return kept, errors
                continue
            if info.st_size > MAX_FILE_BYTES and not is_preview:
                if _err("cplug_too_large", rel, f"{rel[:120]} is over {MAX_FILE_BYTES // 1024} KiB"):
                    return kept, errors
                continue
            if check_magic:
                try:
                    with path.open("rb") as fh:
                        header = fh.read(8)
                except OSError as exc:
                    if _err("cplug_not_safe", rel, f"{rel[:120]} cannot be read ({type(exc).__name__})"):
                        return kept, errors
                    continue
                if zipfile.is_zipfile(path) or (header.startswith(NATIVE_MAGIC) and not is_declared_bin):
                    if _err("cplug_not_safe", rel, f"{rel[:120]} is an executable or archive"):
                        return kept, errors
                    continue
                if rel in view_files and suffix in {".png", ".woff2"}:
                    magic = b"\x89PNG\r\n\x1a\n" if suffix == ".png" else b"wOF2"
                    if not header.startswith(magic):
                        if _err("cplug_not_safe", rel, f"{rel[:120]} does not match its declared file type"):
                            return kept, errors
                        continue
            total += info.st_size
    if total > MAX_TOTAL_BYTES:
        _err("cplug_too_large", "", f"a plugin may total at most {MAX_TOTAL_BYTES // (1024 * 1024)} MiB")
    return kept, errors

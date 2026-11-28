
from __future__ import annotations

from typing import Mapping, Sequence
from urllib.parse import unquote

CSP_DIRECTIVES: tuple[tuple[str, str], ...] = (
    ("default-src", "'self'"),
    ("script-src", "'self'"),
    ("style-src", "'self' 'unsafe-inline'"),
    ("connect-src", "'self' ws: wss:"),
    ("img-src", "'self' data: blob:"),
    ("font-src", "'self' data:"),
    ("frame-ancestors", "'none'"),
)


FRAME_ANCESTORS_SELF: str = "'self'"


def build_csp(script_src_extra: str = "", frame_ancestors: str = "", overrides: "Mapping[str, str] | None" = None,
              extra: "Sequence[str]" = ()) -> str:
    changed = dict(overrides or {})
    parts = []
    for name, value in CSP_DIRECTIVES:
        if name in changed:
            parts.append("%s %s" % (name, changed.pop(name).strip()))
        elif name == "script-src" and script_src_extra:
            parts.append("%s %s %s" % (name, value, script_src_extra.strip()))
        elif name == "frame-ancestors" and frame_ancestors:
            parts.append("%s %s" % (name, frame_ancestors.strip()))
        else:
            parts.append("%s %s" % (name, value))
    parts.extend("%s %s" % (name, value.strip()) for name, value in changed.items())
    parts.extend(d.strip() for d in extra)
    return "; ".join(parts) + ";"


def build_view_csp(base: str) -> str:
    return build_csp(overrides={"default-src": "'none'", "script-src": base, "style-src": f"{base} 'unsafe-inline'", "connect-src": "'none'",
                                "font-src": base, "frame-ancestors": FRAME_ANCESTORS_SELF}, extra=("sandbox allow-scripts",))


CONTENT_SECURITY_POLICY: str = build_csp()

WIDGET_LAB_PATH: str = "/static/dist/widget-lab/index.html"
SELF_FRAMEABLE_PATHS: frozenset[str] = frozenset({"/static/popout.html", WIDGET_LAB_PATH})



def _is_valid_dev_frame_prefix(prefix: object) -> bool:
    if not isinstance(prefix, str) or not prefix.startswith("/") or not prefix.endswith("/"):
        return False
    if (
        "//" in prefix
        or ".." in prefix
        or "%" in prefix
        or "?" in prefix
        or "#" in prefix
        or "\\" in prefix
        or any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in prefix)
    ):
        return False
    segments = prefix.split("/")[1:-1]
    return bool(segments) and not any(seg in ("", ".", "..") for seg in segments)


def dev_frameable_entries() -> tuple[tuple[str, str], ...]:
    from src.plugins.host import runtime  # noqa: PLC0415

    entries: list[tuple[str, str]] = []
    for d in runtime.definitions():
        manifest = getattr(d, "manifest", None)
        if manifest is None or getattr(manifest, "tier", "") != "dev":
            continue
        ui_meta = getattr(manifest, "ui_meta", None)
        prefixes = ui_meta.get("dev_frame_prefixes") if isinstance(ui_meta, Mapping) else None
        if not isinstance(prefixes, (list, tuple)):
            continue
        old_id = getattr(manifest, "renamed_from", "")
        for sub in prefixes:
            if _is_valid_dev_frame_prefix(sub):
                entries.append((f"/api/v1/cplugs/{d.id}{sub}", d.id))
                if isinstance(old_id, str) and old_id:
                    entries.append((f"/api/v1/cplugs/{old_id}{sub}", d.id))
    return tuple(entries)


def dev_frameable_prefixes() -> tuple[str, ...]:
    return tuple(prefix for prefix, _owner_id in dev_frameable_entries())


def dev_prefix_framing_allowed(plugin_id: str) -> bool:
    from src.plugins.host import developer_mode, runtime  # noqa: PLC0415

    try:
        return bool(plugin_id) and developer_mode.is_on() and runtime.current().enabled(plugin_id)
    except (OSError, ValueError, KeyError):
        return False


def _safe_dev_prefix_match(path: str, prefix: str) -> bool:
    for candidate in (path, unquote(path)):
        if (
            not candidate.startswith(prefix)
            or "%" in candidate
            or "\\" in candidate
            or ".." in candidate
            or "//" in candidate
            or "?" in candidate
            or "#" in candidate
            or any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in candidate)
        ):
            return False
        rest = candidate[len(prefix):]
        if rest and any(seg in ("", ".", "..") for seg in rest.split("/")):
            return False
    return True


CONTENT_SECURITY_POLICY_SELF_FRAMEABLE: str = build_csp(frame_ancestors=FRAME_ANCESTORS_SELF)


def csp_for_path(path: str) -> str:
    if not isinstance(path, str):
        return CONTENT_SECURITY_POLICY
    if path in SELF_FRAMEABLE_PATHS:
        return CONTENT_SECURITY_POLICY_SELF_FRAMEABLE
    if (
        path.startswith("/api/v1/cplugs/")
        and "%" not in path
        and "%" not in unquote(path)
        and "\\" not in path
        and "\\" not in unquote(path)
        and ".." not in path
        and ".." not in unquote(path)
        and "//" not in path
        and "//" not in unquote(path)
    ):
        for prefix, owner_id in dev_frameable_entries():
            if _safe_dev_prefix_match(path, prefix) and dev_prefix_framing_allowed(owner_id):
                return CONTENT_SECURITY_POLICY_SELF_FRAMEABLE
    return CONTENT_SECURITY_POLICY


SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

OWN_POLICY_HEADER: str = "X-Carnivore-Own-Policy"


def stamp_security_headers(headers, path: str = "", raw_path: bytes | str = "") -> None:
    own = OWN_POLICY_HEADER in headers
    if own:
        del headers[OWN_POLICY_HEADER]
    raw_str = raw_path.decode("latin-1") if isinstance(raw_path, (bytes, bytearray)) else (raw_path or "")
    for header, value in SECURITY_HEADERS.items():
        if header == "Content-Security-Policy":
            if own and header in headers:
                continue
            value = csp_for_path(path)
            if raw_str and value == CONTENT_SECURITY_POLICY_SELF_FRAMEABLE and csp_for_path(raw_str) != CONTENT_SECURITY_POLICY_SELF_FRAMEABLE:
                value = CONTENT_SECURITY_POLICY
        headers[header] = value


from __future__ import annotations

from typing import Mapping, Sequence

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

DRAFT_HARNESS_PREFIX: str = "/api/v1/cplugs/devwidgetlab/draft-harness/"
DRAFT_PLUGIN_ID: str = "devwidgetlab"


def draft_framing_allowed() -> bool:
    from src.cplugs.host import developer_mode, runtime  # noqa: PLC0415

    try:
        return developer_mode.is_on() and runtime.current().enabled(DRAFT_PLUGIN_ID)
    except (OSError, ValueError, KeyError):
        return False


CONTENT_SECURITY_POLICY_SELF_FRAMEABLE: str = build_csp(frame_ancestors=FRAME_ANCESTORS_SELF)


def csp_for_path(path: str) -> str:
    if path in SELF_FRAMEABLE_PATHS or (path.startswith(DRAFT_HARNESS_PREFIX) and draft_framing_allowed()):
        return CONTENT_SECURITY_POLICY_SELF_FRAMEABLE
    return CONTENT_SECURITY_POLICY


SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

OWN_POLICY_HEADER: str = "X-Carnivore-Own-Policy"


def stamp_security_headers(headers, path: str = "") -> None:
    own = OWN_POLICY_HEADER in headers
    if own:
        del headers[OWN_POLICY_HEADER]
    for header, value in SECURITY_HEADERS.items():
        if header == "Content-Security-Policy":
            if own and header in headers:
                continue
            value = csp_for_path(path)
        headers[header] = value

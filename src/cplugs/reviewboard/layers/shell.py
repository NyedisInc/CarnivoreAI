
from __future__ import annotations

from html import escape

ROOT_ATTRIBUTE = "data-rb-layer-root"

_TEMPLATE = (
    "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<title>{title}</title>\n"
    "<style>\n"
    "html, body {{ margin: 0; background: var(--oc-ground-page); color: var(--oc-text, CanvasText); font-family: var(--font-mono, monospace); }}\n"
    "</style>\n</head>\n<body>\n<main {root}></main>\n</body>\n</html>\n"
)


def shell_page(title: str) -> str:
    return _TEMPLATE.format(title=escape(title, quote=True), root=ROOT_ATTRIBUTE)

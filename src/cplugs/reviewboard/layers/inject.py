
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

FRAME_DIR = Path(__file__).resolve().parent.parent / "frame"
RUNTIME_FILES = ("layer-fields.js", "layer-fields-more.js", "layer-rows.js", "layer-core.js")
STYLE_FILE = "layer.css"
DATA_ID = "rb-layer"
_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", " ": "\\u2028", " ": "\\u2029"}


def data_block(layer: Mapping[str, Any]) -> bytes:
    text = json.dumps(layer, ensure_ascii=False, separators=(",", ":"))
    for char, escaped in _ESCAPES.items():
        text = text.replace(char, escaped)
    return f'<script type="application/json" id="{DATA_ID}">{text}</script>'.encode("utf-8")


def runtime_script() -> bytes:
    body = "\n".join((FRAME_DIR / name).read_text(encoding="utf-8") for name in RUNTIME_FILES)
    return b"<script>(function () {\n" + body.encode("utf-8") + b"\n})();</script>"


def style_block() -> bytes:
    return b"<style data-rb-layer>" + (FRAME_DIR / STYLE_FILE).read_bytes() + b"</style>"


def layer_bytes(layer: Mapping[str, Any]) -> bytes:
    return data_block(layer) + style_block() + runtime_script()

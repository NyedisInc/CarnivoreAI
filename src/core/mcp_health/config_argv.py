
from __future__ import annotations

import json
import os
import re
from typing import Any, List, Optional

from src.config.mcp_launch import CLAUDE_MCP_CONFIG_FLAG

_FLAG_BOUNDARY = re.compile(r"\s+--?[A-Za-z]")


def _path_value(rest: str) -> Optional[str]:
    stop = _FLAG_BOUNDARY.search(rest)
    candidate = (rest[: stop.start()] if stop else rest).rstrip()
    while candidate:
        if os.path.isfile(candidate):
            return candidate
        cut = candidate.rfind(" ")
        if cut <= 0:
            return None
        candidate = candidate[:cut].rstrip()
    return None


def mcp_config_values(command: str) -> List[Any]:
    out: List[Any] = []
    decoder = json.JSONDecoder()
    for match in re.finditer(re.escape(CLAUDE_MCP_CONFIG_FLAG) + r"(=|\s+)", command):
        rest = command[match.end():]
        while rest:
            if rest.startswith("{"):
                try:
                    doc, end = decoder.raw_decode(rest)
                except ValueError:
                    break
                out.append(doc)
                rest = rest[end:]
            else:
                path = _path_value(rest)
                if path is None:
                    break
                out.append(path)
                rest = rest[len(path):]
            if match.group(1) == "=":
                break
            stripped = rest.lstrip()
            if not stripped or stripped.startswith("-"):
                break
            rest = stripped
    return out

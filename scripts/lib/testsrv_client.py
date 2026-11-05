from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Optional

TOKEN_STORAGE_KEY = "claude_tunnel_token"
API_TIMEOUT_S = 20


class TestsrvTokenError(RuntimeError):

    __test__ = False


def access_token(storage_state: str | Path, base: Optional[str] = None) -> str:
    state = json.loads(Path(storage_state).read_text(encoding="utf-8"))
    for origin in state.get("origins", []):
        if base is not None and origin.get("origin") != base:
            continue
        for item in origin.get("localStorage", []):
            if item.get("name") == TOKEN_STORAGE_KEY:
                return str(item["value"])
    where = f" for {base}" if base else ""
    raise TestsrvTokenError(f"no access token in the storage state{where}")


def api(base: str, token: str, path: str, body: Optional[dict] = None, method: Optional[str] = None,
        timeout: float = API_TIMEOUT_S) -> Any:
    req = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"null")

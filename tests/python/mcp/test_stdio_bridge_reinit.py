
from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path
from typing import List

BRIDGE = Path(__file__).resolve().parents[3] / "src" / "core" / "mcp_bridge" / "stdio_bridge.py"


def _load():
    spec = importlib.util.spec_from_file_location("stdio_bridge_under_test", BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_concurrent_reinitialize_opens_one_session() -> None:
    mod = _load()
    up = mod.Upstream.__new__(mod.Upstream)
    up._lock = threading.Lock()
    up._reinit_lock = threading.Lock()
    up.session_id = "old.1"
    up._init_message = {"jsonrpc": "2.0", "method": "initialize", "params": {}}
    initializes: List[int] = []

    class Emitter:
        def emit(self, *_a) -> None:
            return None

    up.emitter = Emitter()

    def fake_call(body: bytes, *_a):
        if b'"initialize"' in body:
            initializes.append(1)
            time.sleep(0.05)
            return 200, {mod.MCP_SESSION_HEADER.lower(): f"new.{len(initializes)}"}, b"{}"
        return 202, {}, b""

    up._call = fake_call
    threads = [threading.Thread(target=up.reinitialize, args=("old.1",)) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(initializes) == 1
    assert up.session_id == "new.1"

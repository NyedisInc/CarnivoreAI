
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from src.core.approvals import beast_policy
from src.core.approvals.beast_policy import GridPolicy
from src.core.mcp import beast_mode


def install(monkeypatch: Any, values: Optional[Dict[str, Any]] = None, *, armed: Optional[Callable[[], bool]] = None,
            prompts: Optional[Callable[[], bool]] = None) -> GridPolicy:
    store = values if values is not None else {}
    policy = GridPolicy(lambda: store, is_armed=armed or beast_mode.stored_armed, is_prompts_armed=prompts or beast_mode.stored_prompts_armed)
    monkeypatch.setattr(beast_policy, "current", lambda: policy)
    return policy


def arm(monkeypatch: Any, armed: Callable[[], bool], values: Optional[Dict[str, Any]] = None) -> GridPolicy:
    monkeypatch.setattr(beast_mode, "beast_enabled", lambda: bool(armed()))
    return install(monkeypatch, values, armed=armed, prompts=lambda: False)

from __future__ import annotations

from typing import Any, Awaitable, Callable

import pytest
from fastapi import HTTPException

from src.api import one_shot_routes
from src.core.sessions import guarded_paste
from src.core.sessions.guarded_paste import PasteRefused

Fake = Callable[..., Awaitable[Any]]


def patch_paste(monkeypatch: pytest.MonkeyPatch, fake: Fake) -> None:
    async def core(app_state: Any, session_id: str, text: str, options: Any = None) -> Any:
        try:
            return await fake(app_state, session_id, text)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            raise PasteRefused(str(detail.get("code") or "refused"), str(detail.get("message") or detail.get("detail") or ""), session_id) from exc

    monkeypatch.setattr(one_shot_routes, "paste_through_gates", fake)
    monkeypatch.setattr(guarded_paste, "paste_through_gates", core)

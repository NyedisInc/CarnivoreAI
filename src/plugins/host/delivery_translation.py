from __future__ import annotations

from typing import Any, Mapping, Optional


async def deliver_translated(request: Any, session_id: str, text: str, meta: Optional[Mapping[str, str]]) -> Any:
    from src.api.one_shot_routes import paste_refusal_to_http  # noqa: PLC0415
    from src.core.sessions.channel_delivery import deliver_through_gates  # noqa: PLC0415
    from src.core.sessions.guarded_paste import PasteRefused  # noqa: PLC0415

    try:
        return await deliver_through_gates(request.app.state, session_id, text, meta)
    except PasteRefused as refusal:
        raise paste_refusal_to_http(refusal) from refusal

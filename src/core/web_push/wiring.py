
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.web_push.sender import PushSender


def sender_for(app_state: Any) -> PushSender:
    sender = getattr(app_state, "web_push_sender", None)
    if sender is None:
        from src.config import settings

        sender = PushSender(settings.get_state_dir(), Path(settings.auth_config_file).expanduser())
        app_state.web_push_sender = sender
    return sender

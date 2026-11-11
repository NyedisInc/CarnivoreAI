
from __future__ import annotations

from typing import Any, Optional

from src.core.notifications import contracts
from src.core.notifications.sources import common

TYPE_ID = "app.update_available"


def on_available(latest_version: str, state_dir: Optional[Any] = None, current_version: str = "") -> bool:
    if not latest_version:
        return False
    event = contracts.NotifyEvent(
        type_id=TYPE_ID, kind="update_check", title=common.type_title(TYPE_ID), ts=common.now(),
        instance_key=f"update:{latest_version}",
        card_hint={"to": latest_version.lstrip("v"), **({"from": current_version.lstrip("v")} if current_version else {})},
    )
    return common.fire_once(TYPE_ID, latest_version, event, state_dir)

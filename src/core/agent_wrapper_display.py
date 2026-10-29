
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class WrapperDisplay:

    wrapper_id: Optional[str] = None
    label: Optional[str] = None
    icon: Optional[str] = None


NO_WRAPPER = WrapperDisplay()


def resolve_wrapper_for_display(
    agent_type: Optional[str],
    wrappers: List,
    *,
    from_fingerprint: bool = False,
) -> WrapperDisplay:
    if from_fingerprint:
        return NO_WRAPPER

    normalized = (agent_type or "").strip().lower()
    if not normalized:
        return NO_WRAPPER

    for wrapper in wrappers:
        if isinstance(wrapper, dict):
            wid = wrapper.get("id")
            label = wrapper.get("label")
            icon = wrapper.get("icon")
        else:
            wid = getattr(wrapper, "id", None)
            label = getattr(wrapper, "label", None)
            icon = getattr(wrapper, "icon", None)
        if not wid or str(wid).strip().lower() != normalized:
            continue
        text = (label or "").strip() or str(wid)
        return WrapperDisplay(wrapper_id=str(wid), label=text, icon=icon or None)

    return NO_WRAPPER


from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, StrictBool, model_serializer

WIDGET_BAR_FIELDS = ("widget_bars", "session_rail", "session_rail_bottom")


class WidgetBar(BaseModel):
    """One bar's chrome. Every key optional; absent reads as show true, size cozy, mode pinned."""

    model_config = ConfigDict(extra="forbid")

    show: Optional[StrictBool] = None
    size: Optional[Literal["compact", "cozy", "detailed"]] = None
    mode: Optional[Literal["autohide", "pinned"]] = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: Any) -> Dict[str, Any]:
        """Store only the keys that were set: ABSENT stays absent, so a default is never written."""
        return {key: value for key, value in handler(self).items() if value is not None}


class SidebarRail(BaseModel):
    """The sidebar rail's chrome (#1790): the slim icon column of ``sidebar_layout`` "rail" hides like a bar.

    Only ``mode`` exists: the rail has no size and is always shown. Absent reads as ``autohide``.
    """

    model_config = ConfigDict(extra="forbid")

    mode: Optional[Literal["autohide", "pinned"]] = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: Any) -> Dict[str, Any]:
        """Store only the keys that were set: ABSENT stays absent, so a default is never written."""
        return {key: value for key, value in handler(self).items() if value is not None}


class WidgetBars(BaseModel):
    """Both bars' chrome plus the sidebar rail's, one value for every device. ``side`` is the right bar.
    """

    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    side: Optional[WidgetBar] = None
    bottom: Optional[WidgetBar] = None
    together: Optional[Literal["both", "one"]] = None
    rail: Optional[SidebarRail] = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: Any) -> Dict[str, Any]:
        """Store only the keys that were set: ABSENT stays absent, so a default is never written."""
        return {key: value for key, value in handler(self).items() if value is not None}

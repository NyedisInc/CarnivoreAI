
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt


class ItemSettingsPatch(BaseModel):
    """What one write may change.

    Attributes:
        values: field key -> new value, or None to clear the choice.
        enabled: the on/off choice, for a switchable widget.
        expected_revision: the item revision the caller read (0 for an
          item never written); omitted means "last write wins".
    """

    model_config = ConfigDict(extra="forbid")

    values: Optional[Dict[str, Any]] = None
    enabled: Optional[StrictBool] = None
    expected_revision: Optional[StrictInt] = None

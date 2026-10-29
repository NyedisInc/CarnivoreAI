
from typing import Optional

from pydantic import BaseModel, Field

BROWSER_KEY = "browser"


class BrowserConfig(BaseModel):
    """Limits and the binary for headless browser sessions.

    Fields:
        max_live: the most Chromium processes alive at once (decision D11).
            Creating or opening past it is REFUSED with a sentence naming
            the cap, never by silently stopping the oldest.
        idle_stop_minutes: minutes with no viewer before a live browser is
            stopped. The row and profile stay; the next open relaunches.
        executable: an explicit Chromium or Chrome binary. When unset the
            ladder is Google Chrome, then Playwright's headless shell.
    """

    max_live: int = Field(default=4, ge=1, le=32)
    idle_stop_minutes: float = Field(default=15, gt=0, le=24 * 60)
    executable: Optional[str] = None

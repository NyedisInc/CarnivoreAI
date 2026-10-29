
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.browsers.store import MAX_LABEL_LENGTH
from src.core.browsers.url_policy import MAX_URL_LENGTH
from src.models.row_looks import look_checked


class BrowserInfo(BaseModel):
    """One browser session as a client sees it."""

    id: str = Field(..., description="16 lowercase hex characters.")
    label: str = Field(..., description="The drawer row's name.")
    url: str = Field(
        ...,
        description="The page a reopen goes to, WITHOUT query or fragment (D7).",
    )
    state: str = Field(..., description="'live' (a Chromium is running) or 'stopped'.")
    viewers: int = Field(..., description="Connected viewer sockets; 0 when stopped.")
    created_at: str = Field(..., description="ISO-8601 UTC.")
    updated_at: str = Field(..., description="ISO-8601 UTC.")


class BrowserList(BaseModel):
    """``GET /browsers``: every stored session, oldest first."""

    browsers: List[BrowserInfo]


class CreateBrowserRequest(BaseModel):
    """``POST /browsers``. Both fields optional."""

    url: Optional[str] = Field(
        None, max_length=MAX_URL_LENGTH,
        description="Where to open. Absent or blank means about:blank. A bare "
                    "host gets https:// (http:// for loopback).",
    )
    label: Optional[str] = Field(
        None, max_length=MAX_LABEL_LENGTH,
        description="The row's name. Absent means the URL's host, or 'browser'.",
    )


class RenameBrowserRequest(BaseModel):
    """``PATCH /browsers/{id}``."""

    label: str = Field(..., min_length=1, max_length=MAX_LABEL_LENGTH)


class NavigateBrowserRequest(BaseModel):
    """``POST /browsers/{id}/navigate``."""

    url: str = Field(..., max_length=MAX_URL_LENGTH)


class TaskManagerArtifactRef(BaseModel):
    """One agent page on a huddle item: the item id and the artifact id ``huddle_artifact`` answered."""

    model_config = ConfigDict(extra="forbid")
    item: int = Field(..., ge=1)
    artifact: str = Field(..., pattern=r"^[0-9a-f]{8}$")


class OpenPageRequest(BaseModel):
    """``POST /browsers/open`` (``docs/browser-pages.md``): exactly one of ``url`` (an app pop-out path or an http(s) site) or ``huddle_artifact``, and a title."""

    model_config = ConfigDict(extra="forbid")
    url: Optional[str] = Field(None, min_length=1, max_length=MAX_URL_LENGTH)
    huddle_artifact: Optional[TaskManagerArtifactRef] = None
    title: str = Field("", max_length=MAX_LABEL_LENGTH, description="The page or browser row label; default the page's own title or the host.")
    color: Optional[str] = Field(None, description="OPTIONAL named theme color for the row (docs/row-looks.md).")
    icon: Optional[str] = Field(None, description="OPTIONAL named icon for the row (docs/row-looks.md).")

    @model_validator(mode="after")
    def _exactly_one(self) -> "OpenPageRequest":
        if (self.url is None) == (self.huddle_artifact is None):
            raise ValueError("send exactly one of url or huddle_artifact")
        look_checked(self.color, self.icon)
        return self

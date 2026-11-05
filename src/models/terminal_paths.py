
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from src.core.terminal_paths.resolve import MAX_TEXT

MAX_CANDIDATES = 32


class ResolvePathsRequest(BaseModel):
    """The path texts one terminal row shows, as printed (``src/a.py:12``, ``~/x``, ``/tmp/y``)."""

    texts: List[str] = Field(..., min_length=1, max_length=MAX_CANDIDATES)


class ResolvedPath(BaseModel):
    """One candidate's answer: the absolute path and its kind, or both null when nothing by that name exists."""

    text: str
    path: Optional[str] = None
    kind: Optional[Literal["file", "dir"]] = None
    line: Optional[int] = None


class ResolvePathsResponse(BaseModel):
    """One answer per candidate, in the request's order."""

    paths: List[ResolvedPath]


class OpenPathRequest(BaseModel):
    """Open one printed path outside Carnivore: Finder shows it, or the default browser opens it (files only)."""

    text: str = Field(..., min_length=1, max_length=MAX_TEXT)
    app: Literal["finder", "browser"]


class OpenPathResponse(BaseModel):
    """What was opened."""

    path: str
    app: Literal["finder", "browser"]

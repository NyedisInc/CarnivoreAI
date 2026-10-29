
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

BuiltinKind = Literal["cplug", "theme", "skill"]


class BuiltinEntry(BaseModel):
    """One thing the app carries itself.

    Inputs (constructor): id (str) - ``<publisher>/<name>``, ``nyedis/`` for plugins and themes, ``carnivore/`` for skills.
      kind (BuiltinKind). name (str) - the display name. version (str). since_app_version (str | None) - the first app version
      that carries it, None when the build cannot say. until_app_version (str | None) - set once it leaves the binary.
      source (str) - always ``builtin``.
    Example: BuiltinEntry(id="nyedis/flow", kind="cplug", name="flow chart", version="1.0.0")
    """

    id: str
    kind: BuiltinKind
    name: str
    version: str
    since_app_version: Optional[str] = None
    until_app_version: Optional[str] = None
    source: Literal["builtin"] = "builtin"


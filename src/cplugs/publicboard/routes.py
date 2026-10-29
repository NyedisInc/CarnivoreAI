
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Tuple

Handler = Callable[[Any, Any, Any], Awaitable[None]]
RouteKey = Tuple[str, str]

ROUTES: Mapping[RouteKey, Handler] = MappingProxyType({})

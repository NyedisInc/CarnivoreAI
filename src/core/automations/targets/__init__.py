
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

Runner = Callable[[Any, Dict[str, Any], Dict[str, Any]], Awaitable[Any]]
Validator = Callable[[Dict[str, Any]], Optional[str]]

LoginHint = Callable[[Any, Dict[str, Any]], Awaitable[Optional[str]]]

RUNNERS: Dict[str, Runner] = {}
LOGIN_HINTS: Dict[str, LoginHint] = {}
VALIDATORS: Dict[str, Validator] = {}

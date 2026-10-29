
from __future__ import annotations

from typing import Any, Protocol


class Executor(Protocol):

    @property
    def in_transaction(self) -> bool:
        ...

    def execute(self, sql: str, params: Any = ...) -> Any:
        ...

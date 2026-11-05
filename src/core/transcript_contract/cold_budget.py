
from __future__ import annotations

from typing import BinaryIO, Protocol


class LineSource(Protocol):

    def readline(self) -> bytes: ...

    def tell(self) -> int: ...


class BudgetedHandle:

    def __init__(self, handle: BinaryIO, budget: int) -> None:
        self._handle = handle
        self._budget = budget
        self._spent = 0
        self.exhausted: bool = False

    def readline(self) -> bytes:
        if self._spent >= self._budget:
            self.exhausted = True
            return b""
        line = self._handle.readline()
        self._spent += len(line)
        return line

    def tell(self) -> int:
        return self._handle.tell()

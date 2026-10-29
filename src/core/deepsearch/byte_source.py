
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, Iterator, Optional, Protocol, Tuple, Union

from src.core.deepsearch import constants as K
from src.core.deepsearch import fallback_hook as fb


class SourceGone(OSError):
    pass


class ByteSource(Protocol):

    length: int

    def read(self, offset: int, length: int) -> bytes:
        pass

    def lines(self, start: int, end: int) -> Iterator[Tuple[int, bytes]]:
        pass


class DiskSource:

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)

    @property
    def length(self) -> int:
        return os.stat(self.path).st_size

    def read(self, offset: int, length: int) -> bytes:
        with open(self.path, "rb") as handle:
            handle.seek(offset)
            return handle.read(length)

    def lines(self, start: int, end: int) -> Iterator[Tuple[int, bytes]]:
        from src.core.deepsearch.live.reader import RangeReader  # noqa: PLC0415

        return iter(RangeReader(self.path, start, end))


class VaultSource:

    def __init__(self, reader) -> None:
        self._reader = reader
        self.length = int(reader.length)

    def read(self, offset: int, length: int) -> bytes:

        try:
            return self._reader.read(offset, length)
        except fb.FallbackUnavailable as exc:
            raise SourceGone(str(exc)) from exc

    def lines(self, start: int, end: int) -> Iterator[Tuple[int, bytes]]:

        try:
            yield from self._reader.lines(start, end)
        except fb.FallbackUnavailable as exc:
            raise SourceGone(str(exc)) from exc


def is_vault_mark(mark: Optional[str]) -> bool:
    return mark == K.VAULT_MARK


def open_source(path: str, mark: Optional[str], conversation_id: str, file_kind: str, *,
                sources: Optional[Iterable] = None) -> ByteSource:
    if not is_vault_mark(mark):
        return DiskSource(path)

    unreachable: Optional[OSError] = None
    for source in (fb.sources() if sources is None else sources):
        try:
            return VaultSource(source.reader(conversation_id, path, file_kind))
        except fb.FallbackUnavailable:
            continue
        except OSError as exc:
            unreachable = exc
    if unreachable is not None:
        raise unreachable
    raise SourceGone(f"no backup source holds {file_kind} file of {conversation_id}")


class SourceCache:

    def __init__(self) -> None:
        self._items: Dict[int, Union[ByteSource, OSError]] = {}

    def get(self, live_id: int, path: str, mark: Optional[str], conversation_id: str, file_kind: str) -> ByteSource:
        if live_id not in self._items:
            try:
                self._items[live_id] = open_source(path, mark, conversation_id, file_kind)
            except OSError as exc:
                self._items[live_id] = exc
        item = self._items[live_id]
        if isinstance(item, OSError):
            raise item
        return item

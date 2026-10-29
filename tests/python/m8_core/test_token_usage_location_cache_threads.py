from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import List

from src.core.session_token_usage import reader


def test_hammering_the_cache_from_many_threads_never_raises() -> None:
    cache: "OrderedDict[tuple, Path]" = OrderedDict()
    errors: List[BaseException] = []

    def work(offset: int) -> None:
        try:
            for i in range(3000):
                key = (None, f"uuid-{(i + offset) % 400}")
                reader._remember_location(cache, key, Path("/tmp/x"))
                reader._cached_location(cache, (None, f"uuid-{(i * 7 + offset) % 400}"))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n * 53,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(cache) <= reader._LOCATION_CACHE_MAX


def test_every_cache_access_takes_the_lock(monkeypatch) -> None:
    held: List[str] = []

    class _Spy:
        def __enter__(self) -> None:
            held.append("in")

        def __exit__(self, *_exc: object) -> None:
            held.append("out")

    monkeypatch.setattr(reader, "_LOCATION_LOCK", _Spy())
    cache: "OrderedDict[tuple, Path]" = OrderedDict()
    reader._remember_location(cache, (None, "u"), Path("/tmp/x"))
    reader._cached_location(cache, (None, "u"))
    reader.reset_location_caches_for_tests()
    assert held == ["in", "out"] * 3

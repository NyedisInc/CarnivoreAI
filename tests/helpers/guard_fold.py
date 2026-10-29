
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import pytest

_RAISED = (Exception, pytest.fail.Exception, pytest.skip.Exception)


def assert_no_offenders(
    rule: str,
    items: Iterable[Any],
    check: Callable[[Any], None],
    label: Callable[[Any], str] = str,
) -> None:
    items = list(items)
    assert items, f"{rule}: handed nothing to check, so it would pass vacuously"
    found: list[str] = []
    for item in items:
        try:
            check(item)
        except _RAISED as exc:
            found.append(f"  {label(item)}: {type(exc).__name__}: {exc}")
    assert not found, (
        f"{rule}: {len(found)} of {len(items)} offend\n" + "\n".join(found)
    )

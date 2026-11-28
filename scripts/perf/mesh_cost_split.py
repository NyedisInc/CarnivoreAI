
from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Tuple

Lock = Tuple[float, float, float]
HopSample = Tuple[float, float, float]
DEEP_LIMIT = 5_000_000


def timed_transaction(orig: Callable[[Any], Any], locks: List[Lock], armed: Callable[[], bool]) -> Callable[[Any], Any]:

    @contextmanager
    def transaction(conn: Any) -> Iterator[Any]:
        asked, got = time.perf_counter(), None
        try:
            with orig(conn) as inner:
                got = time.perf_counter()
                yield inner
        finally:
            if got is not None and armed():
                locks.append(((got - asked) * 1000, got, time.perf_counter()))

    return transaction


def _p95(values: List[float]) -> Any:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, -(-95 * len(ordered) // 100) - 1)]


def _part(values: List[float]) -> Dict[str, Any]:
    ordered = sorted(values)
    return {"p50": ordered[len(ordered) // 2] if ordered else None, "p95": _p95(values), "n": len(values)}


def hop_split(samples: Dict[str, List[HopSample]], locks: List[Lock]) -> Dict[str, Any]:
    held = sorted((got, end) for _, got, end in locks)
    out: Dict[str, Any] = {}
    for name, rows in samples.items():
        over, clear, waits, cpus = [], [], [], []
        for start, end, cpu in rows:
            inside = (end - start) * 1000
            (over if any(g <= end and e >= start for g, e in held) else clear).append(inside)
            waits.append(max(0.0, inside - cpu))
            cpus.append(cpu)
        out[name] = {"overlap": _part(over), "clear": _part(clear), "wait_p95": _p95(waits), "cpu": _part(cpus)}
    return out


def lock_summary(locks: List[Lock]) -> Dict[str, Any]:
    return {"count": len(locks), "held_p95": _p95([(e - g) * 1000 for _, g, e in locks]), "wait_p95": _p95([w for w, _, _ in locks])}


def deep_size(root: Any) -> Dict[str, Any]:
    seen, stack, total = set(), [root], 0
    while stack and len(seen) < DEEP_LIMIT:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        total += sys.getsizeof(obj)
        if isinstance(obj, dict):
            stack.extend(obj.keys())
            stack.extend(obj.values())
        elif isinstance(obj, (list, tuple, set, frozenset)):
            stack.extend(obj)
        elif isinstance(obj, (str, bytes, bytearray, int, float, bool, type(None))):
            continue
        else:
            if hasattr(obj, "__dict__"):
                stack.append(obj.__dict__)
            for cls in type(obj).__mro__:
                for slot in getattr(cls, "__slots__", ()) or ():
                    if hasattr(obj, slot):
                        stack.append(getattr(obj, slot))
    return {"bytes": total, "objects": len(seen), "truncated": bool(stack)}

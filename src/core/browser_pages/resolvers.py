
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict

PATH_PREFIX = "/api/v1/"


class PageKindUnavailable(LookupError):
    pass


class PageNotFound(LookupError):
    pass


@dataclass(frozen=True)
class ResolvedPage:

    path: str
    title: str


Resolver = Callable[[dict], Awaitable[ResolvedPage]]

_lock = threading.Lock()
_resolvers: Dict[str, Resolver] = {}


def register(kind: str, resolver: Resolver) -> None:
    with _lock:
        _resolvers[kind] = resolver


def unregister(kind: str) -> None:
    with _lock:
        _resolvers.pop(kind, None)


async def resolve(kind: str, ref: dict) -> ResolvedPage:
    with _lock:
        resolver = _resolvers.get(kind)
    if resolver is None:
        raise PageKindUnavailable(kind)
    page = await resolver(ref)
    if not page.path.startswith(PATH_PREFIX):
        raise ValueError(f"resolver for {kind} answered a path outside {PATH_PREFIX}")
    return page


def reset_for_test() -> None:
    with _lock:
        _resolvers.clear()


__all__ = ["PATH_PREFIX", "PageKindUnavailable", "PageNotFound", "ResolvedPage", "Resolver", "register", "reset_for_test",
           "resolve", "unregister"]

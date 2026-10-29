
from __future__ import annotations

import inspect
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Awaitable, Callable, Iterable, Optional, Union

import structlog

from src.core.boot.teardown import TeardownRunner

if TYPE_CHECKING:
    from src.core.boot.context import BootContext

logger = structlog.get_logger()

StepFn = Callable[["BootContext"], Union[None, Awaitable[None]]]


class BootRegistryError(ValueError):
    pass


class FailureMode(str, Enum):

    FATAL = "fatal"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class BootStep:

    name: str
    order: int
    start: Optional[StepFn] = None
    stop: Optional[StepFn] = None
    failure: FailureMode = FailureMode.FATAL
    degrades_on: tuple[type[Exception], ...] = ()
    failure_event: str = ""
    swallow_reason: str = ""
    stop_order: Optional[int] = None
    stop_requires: tuple[str, ...] = ()
    stop_after_failed_start: bool = False
    stop_name: str = ""
    stop_parts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.failure is FailureMode.DEGRADED and not (self.degrades_on and self.failure_event):
            raise BootRegistryError(f"degraded step {self.name!r} needs degrades_on and failure_event")
        if self.failure is FailureMode.FATAL and self.degrades_on:
            raise BootRegistryError(f"fatal step {self.name!r} cannot name degrades_on")
        if Exception in self.degrades_on and not self.swallow_reason:
            raise BootRegistryError(f"step {self.name!r} swallows every Exception without a swallow_reason")
        if self.stop_name and self.stop_parts:
            raise BootRegistryError(f"step {self.name!r} names both stop_name and stop_parts")

    @property
    def teardown_names(self) -> tuple[str, ...]:
        if self.stop is None:
            return ()
        return self.stop_parts or (self.stop_name or self.name,)

    @property
    def effective_stop_order(self) -> int:
        return self.order if self.stop_order is None else self.stop_order


class BootRegistry:

    def __init__(self, steps: Iterable[BootStep] = ()) -> None:
        self._steps: list[BootStep] = []
        for step in steps:
            self._add(step)
        self._check_requires()

    def register(self, step: BootStep) -> None:
        self._add(step)
        try:
            self._check_requires()
        except BootRegistryError:
            self._steps.remove(step)
            raise

    def _check_requires(self) -> None:
        stops_at: dict[str, int] = {}
        for held in self._steps:
            for name in held.teardown_names:
                if name in stops_at:
                    raise BootRegistryError(f"teardown name {name!r} is used twice")
                stops_at[name] = held.effective_stop_order
        for held in self._steps:
            for required in held.stop_requires:
                if required not in stops_at:
                    raise BootRegistryError(f"step {held.name!r} requires unknown teardown name {required!r}")
                if stops_at[required] <= held.effective_stop_order:
                    raise BootRegistryError(f"step {held.name!r} requires {required!r}, which is torn down after it")

    def _add(self, step: BootStep) -> None:
        for held in self._steps:
            if held.name == step.name:
                raise BootRegistryError(f"duplicate boot step name {step.name!r}")
            if held.order == step.order:
                raise BootRegistryError(f"boot steps {held.name!r} and {step.name!r} share order {step.order}")
            if held.effective_stop_order == step.effective_stop_order and (held.stop and step.stop):
                raise BootRegistryError(f"boot steps {held.name!r} and {step.name!r} share stop order {step.effective_stop_order}")
        self._steps.append(step)

    def start_sequence(self) -> list[BootStep]:
        return sorted(self._steps, key=lambda step: step.order)

    def stop_sequence(self) -> list[BootStep]:
        return sorted((s for s in self._steps if s.stop is not None), key=lambda s: s.effective_stop_order, reverse=True)


async def _call(fn: StepFn, ctx: "BootContext") -> None:
    result = fn(ctx)
    if inspect.isawaitable(result):
        await result


class BootRunner:

    def __init__(self, registry: BootRegistry, *, log: Optional[structlog.stdlib.BoundLogger] = None) -> None:
        self._registry = registry
        self._log = log or logger
        self._stoppable: set[str] = set()

    async def start_all(self, ctx: "BootContext") -> None:
        for step in self._registry.start_sequence():
            try:
                if step.start is not None:
                    await _call(step.start, ctx)
            except step.degrades_on as exc:
                self._log.warning(step.failure_event, error=str(exc), step=step.name)
                if step.stop_after_failed_start:
                    self._stoppable.add(step.name)
                continue
            except Exception:
                await self._rollback(ctx)
                raise
            self._stoppable.add(step.name)

    async def stop_all(self, ctx: "BootContext") -> None:
        teardown = TeardownRunner(self._log)
        ctx.teardown = teardown
        for step in self._registry.stop_sequence():
            if step.name not in self._stoppable or step.stop is None:
                continue
            self._stoppable.discard(step.name)
            ctx.allowed_parts = frozenset(step.stop_parts)
            name = step.name if step.stop_parts else step.teardown_names[0]
            await teardown.run(name, _bound(step.stop, ctx), requires=step.stop_requires)
        ctx.allowed_parts = frozenset()

    async def _rollback(self, ctx: "BootContext") -> None:
        await self.stop_all(ctx)


def _bound(fn: StepFn, ctx: "BootContext") -> Callable[[], Union[None, Awaitable[None]]]:
    return lambda: fn(ctx)


_TEARDOWN_BASE = 10_000


def teardown_slot(position: int) -> int:
    return _TEARDOWN_BASE - position

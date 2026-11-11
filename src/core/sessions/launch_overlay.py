
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Protocol, Tuple


@dataclass(frozen=True)
class OverlayPlan:

    preamble: str
    env_names: Tuple[str, ...] = ()
    secret_name: str = ""
    direct_value: str = "-"
    flags: Tuple[str, ...] = ()
    reason: str = ""
    chained: bool = False
    replaces_flags: bool = False
    upstream_url: str = ""


@dataclass(frozen=True)
class UpstreamRoute:

    base_url: str
    key_env: str = ""
    flags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class OverlayContext:

    harness: str
    session_ref: str = ""
    working_dir: str = ""
    display_name: str = ""
    host_key: str = "local"
    resume_uuid: str = ""
    settings_override: Optional[bool] = None


@dataclass(frozen=True)
class OverlayDelivery:

    secrets: Mapping[str, str] = field(default_factory=dict)
    note: Mapping[str, Any] = field(default_factory=dict)


class LaunchOverlay(Protocol):

    def plan(self, harness: str, purpose: str, host_key: str = "local") -> Optional[OverlayPlan]:
        pass

    async def materialize(self, plan: OverlayPlan, ctx: OverlayContext) -> OverlayDelivery:
        pass

    def chain_plan(self, harness: str, purpose: str, route: "UpstreamRoute") -> Optional[OverlayPlan]:
        pass

    async def prepare_host(self, host_key: str) -> None:
        pass

    async def confirm(self, session_ref: str) -> None:
        pass


class OverlayRefused(RuntimeError):

    def __init__(self, reason: str) -> None:
        super().__init__(f"launch refused: {reason}")
        self.reason = reason


_overlay: Optional[LaunchOverlay] = None


def register(overlay: Optional[LaunchOverlay]) -> None:
    global _overlay
    _overlay = overlay


def get() -> Optional[LaunchOverlay]:
    return _overlay


def plan_for(harness: str, purpose: str, host_key: str = "local") -> Optional[OverlayPlan]:
    return _overlay.plan(harness, purpose, host_key) if _overlay is not None else None


def chain_plan_for(harness: str, purpose: str, route: UpstreamRoute) -> Optional[OverlayPlan]:
    return _overlay.chain_plan(harness, purpose, route) if _overlay is not None else None


async def prepare_host(host_key: str) -> None:
    if _overlay is not None:
        await _overlay.prepare_host(host_key)


async def confirm(session_ref: str) -> None:
    if _overlay is not None:
        await _overlay.confirm(session_ref)


def direct_secrets(plan: OverlayPlan) -> Dict[str, str]:
    return {plan.secret_name: plan.direct_value}


from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Sequence, Tuple, Union

from fastapi import APIRouter

from src.cplugs.sdk.manifest import Manifest
from src.cplugs.sdk.storage import CoreStorageSpec, StorageSpec

GATES = ("read", "agent", "agent_direct", "inbox")

ToolHandler = Callable[[Any, Any, dict], Awaitable[dict]]
LifecycleHook = Callable[[Any], Awaitable[None]]


@dataclass(frozen=True)
class ToolSpec:

    description: str
    properties: Mapping[str, Any]
    required: Sequence[str]
    handler: ToolHandler
    gate: str = "read"
    prepare: Optional[Callable[[Any, Any, dict], Awaitable[Tuple[dict, str]]]] = None
    dedupe_by: Sequence[str] = ()
    on_deny: Optional[Callable[[Any, dict], None]] = None
    canonical_args: Optional[Callable[[dict], dict]] = None
    max_body_bytes: int = 0
    pane_only_args: Sequence[str] = ()
    capability_id: str = ""
    summary: str = ""


def with_capabilities(tools: Mapping[str, ToolSpec], table: Mapping[str, Tuple[str, str]]) -> Dict[str, ToolSpec]:
    missing, extra = sorted(set(tools) - set(table)), sorted(set(table) - set(tools))
    if missing or extra:
        raise ValueError(f"capability table mismatch: no row for {missing}, no tool for {extra}")
    return {name: replace(spec, capability_id=table[name][0], summary=table[name][1]) for name, spec in tools.items()}


@dataclass(frozen=True)
class SettingsWarning:

    code: str
    message: str
    field: str = ""
    detail: str = ""

    def as_wire(self) -> Dict[str, str]:
        out = {"code": self.code, "message": self.message}
        if self.field:
            out["field"] = self.field
        if self.detail:
            out["detail"] = self.detail
        return out


PLAIN_ADVICE_CODE = "advice"


def as_warning(item: Union[str, SettingsWarning]) -> SettingsWarning:
    return item if isinstance(item, SettingsWarning) else SettingsWarning(PLAIN_ADVICE_CODE, str(item))


@dataclass(frozen=True)
class SettingsVerdict:

    refusal: str = ""
    warnings: Tuple[Union[str, SettingsWarning], ...] = ()


SettingsCheck = Callable[[Mapping[str, Any]], SettingsVerdict]


@dataclass(frozen=True)
class CplugDefinition:

    manifest: Manifest
    router: Optional[APIRouter] = None
    tools: Mapping[str, ToolSpec] = field(default_factory=dict)
    storage: Optional[Union[StorageSpec, CoreStorageSpec]] = None
    on_start: Optional[LifecycleHook] = None
    on_stop: Optional[LifecycleHook] = None
    on_settings: Optional[LifecycleHook] = None
    settings_check: Optional[SettingsCheck] = None

    @property
    def id(self) -> str:
        return self.manifest.id

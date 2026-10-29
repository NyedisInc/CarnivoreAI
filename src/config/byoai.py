
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config.byoai_extra_body import EXTRA_BODY_OPTION, parse_extra_body
from src.core.byoai.contracts import REGION

BYOAI_KEY = "byoai"

CONNECTION_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")

_SECRETISH = re.compile(r"key|token|secret|password|passwd|authorization|credential", re.I)

_OPTION_NAME_ALLOWED = frozenset({"auth_header"})


class ModelOverride(BaseModel):
    """What the owner ticked or unticked for one model of a connection."""

    model_config = ConfigDict(extra="forbid")

    capabilities: List[str] = Field(default_factory=list)
    flags: List[str] = Field(default_factory=list)
    enabled: bool = True


class TargetRef(BaseModel):
    """A connection + model (+ voice for speech) a default or a feature points at."""

    model_config = ConfigDict(extra="forbid")

    connection: str
    model: Optional[str] = None
    voice: Optional[str] = None


class ConnectionConfig(BaseModel):
    """One configured endpoint, without its secret."""

    model_config = ConfigDict(extra="forbid")

    id: str
    preset: str
    label: str = ""
    base_url: str = ""
    options: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    key_host: Optional[str] = None
    key_hint: str = Field(default="", max_length=4)
    models: Dict[str, ModelOverride] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not CONNECTION_ID.fullmatch(value):
            raise ValueError("connection id must be lowercase letters, digits, - or _ (max 48)")
        return value

    @field_validator("options")
    @classmethod
    def _options_hold_no_secret(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        for name, item in value.items():
            if name not in _OPTION_NAME_ALLOWED and _SECRETISH.search(name):
                raise ValueError(f"option name {name!r} looks like a secret; keys live in the Keychain")
            scalar = item is None or isinstance(item, (str, int, float, bool))
            strings = isinstance(item, list) and all(isinstance(x, str) for x in item)
            if not (scalar or strings):
                raise ValueError(f"option {name!r} must be a scalar or a list of strings")
        region = value.get("region")
        if region not in (None, "") and not (isinstance(region, str) and REGION.fullmatch(region)):
            raise ValueError("region must look like us-east-1")
        parse_extra_body(value.get(EXTRA_BODY_OPTION))
        return value


class ByoaiConfig(BaseModel):
    """The whole block. ``revision`` counts writes; a stale write is refused.

    ``defaults`` maps a capability to a target; ``features`` maps a registered
    feature id to a target. No fallback chains.
    """

    model_config = ConfigDict(extra="forbid")

    revision: int = 0
    connections: List[ConnectionConfig] = Field(default_factory=list)
    defaults: Dict[str, TargetRef] = Field(default_factory=dict)
    features: Dict[str, TargetRef] = Field(default_factory=dict)

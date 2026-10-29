
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlacementModel(BaseModel):
    """The BYOAI target for enhanced placement (P7 reads it)."""

    model_config = ConfigDict(extra="forbid")

    connection: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=200)


class PackSettings(BaseModel):
    """The document. ``rev`` is ``[counter, install_id]``."""

    model_config = ConfigDict(extra="forbid")

    master_install_id: str = Field(min_length=1, max_length=64)
    placement_mode: Literal["stats", "enhanced"] = "stats"
    auto_distribute: bool = False
    placement_model: Optional[PlacementModel] = None
    rev: Tuple[int, str]

    @field_validator("rev")
    @classmethod
    def _rev(cls, value: Tuple[int, str]) -> Tuple[int, str]:
        if value[0] < 0 or not value[1] or len(value[1]) > 64:
            raise ValueError("rev is [counter, install_id]")
        return value


def default_doc(master_install_id: str) -> PackSettings:
    return PackSettings(master_install_id=master_install_id, rev=(0, master_install_id))


def from_dict(raw: Any) -> Optional[PackSettings]:
    if not isinstance(raw, dict):
        return None
    try:
        return PackSettings(**raw)
    except (TypeError, ValueError):
        return None


def newer(a: PackSettings, b: PackSettings) -> bool:
    return tuple(a.rev) > tuple(b.rev)


def edited(current: PackSettings, changes: Dict[str, Any], self_install_id: str) -> PackSettings:
    base = current.model_dump()
    base.update(changes)
    base["rev"] = (current.rev[0] + 1, self_install_id)
    return PackSettings(**base)


def digest(doc: PackSettings) -> str:
    body = json.dumps(doc.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()[:16]


from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.machines import roster_doc, settings_sign
from src.core.pack.machines.roster_doc import RosterComputer, RosterInput
from src.core.pack.machines.settings_sign import Signature, Verdict
from src.core.relay_identity.device_key import DeviceKey

SIGN_PREFIX_V2 = b"carnivore pack roster v2\x00"
MAX_COMPUTERS_V2 = 64
MAX_CAPS = 64
MAX_BLOB_BYTES = 768 * 1024
BUMP_REASONS_V2 = roster_doc.BUMP_REASONS + ("authority",)
_AUTHORITY = ("one_way", "link_peers", "link_at", "may_receive_logins")
_INTERIM_HINTS = frozenset({"label", "addresses", "link_port", "capabilities", "laptop"})


class RosterComputerV2(RosterComputer):

    model_config = ConfigDict(extra="forbid")

    mesh: bool = False
    link_peers: bool = True
    link_at: int = Field(default=0, ge=0)
    one_way: bool = False
    may_receive_logins: bool = False
    capabilities: List[str] = Field(default_factory=list, max_length=MAX_CAPS)
    laptop: bool = False

    @field_validator("capabilities")
    @classmethod
    def _caps(cls, value: List[str]) -> List[str]:
        if any(not (0 < len(c) <= 64 and c.isprintable()) for c in value):
            raise ValueError("a capability is not short printable text")
        return value


class RosterV2(BaseModel):
    """The v2 document: the v1 top fields, up to 64 entries in successor order."""

    model_config = ConfigDict(extra="forbid")

    generation: int = Field(ge=0)
    alpha: str = Field(min_length=1, max_length=64)
    home: str = Field(min_length=1, max_length=64)
    issued_at: int = Field(ge=0)
    computers: List[RosterComputerV2] = Field(min_length=1, max_length=MAX_COMPUTERS_V2)

    @model_validator(mode="after")
    def _consistent(self) -> "RosterV2":
        ids = self.order()
        if len(set(ids)) != len(ids):
            raise ValueError("a computer is listed twice")
        if self.alpha not in ids:
            raise ValueError("the alpha is not in the roster")
        if any(c.link_at > self.generation for c in self.computers):
            raise ValueError("a link switch stamp is from the future")
        return self

    def entry(self, install_id: str) -> Optional[RosterComputerV2]:
        return next((c for c in self.computers if c.install_id == install_id), None)

    def order(self) -> List[str]:
        return [c.install_id for c in self.computers]

    def as_v1(self) -> roster_doc.Roster:
        drop = set(RosterComputerV2.model_fields) - set(RosterComputer.model_fields)
        return roster_doc.Roster(**{**self.model_dump(exclude={"computers"}),
                                    "computers": [c.model_dump(exclude=drop) for c in self.computers]})


def canonical_bytes_v2(roster: RosterV2) -> bytes:
    body = json.dumps(roster.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return SIGN_PREFIX_V2 + body.encode("ascii")


def sign_v2(roster: RosterV2, key: DeviceKey, signer: str) -> Signature:
    return Signature(signer, key.sign(canonical_bytes_v2(roster)))


def verify_v2(roster: RosterV2, signature: Signature, public_key_b64: str) -> bool:
    return settings_sign.verify_bytes(canonical_bytes_v2(roster), signature, public_key_b64)


def to_wire_v2(roster: RosterV2, signature: Dict[str, Any]) -> Dict[str, Any]:
    return {"roster": roster.model_dump(mode="json"), "sig": signature}


def from_wire_v2(raw: Any) -> Optional[Tuple[RosterV2, Optional[Signature]]]:
    if not isinstance(raw, dict) or not isinstance(raw.get("roster"), dict):
        return None
    try:
        return RosterV2(**raw["roster"]), settings_sign.signature_from(raw.get("sig"))
    except (TypeError, ValueError):
        return None


def blob(wire: Dict[str, Any]) -> bytes:
    return json.dumps(wire, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plan_v2(held: Optional[RosterV2], inputs: Sequence[RosterInput], *, alpha: str, home: Optional[str] = None,
            eligible: Optional[Dict[str, bool]] = None, order: Optional[Sequence[str]] = None,
            link_peers: Optional[Dict[str, bool]] = None, source: Optional[Mapping[str, bool]] = None,
            default_on: bool = True) -> Optional[RosterV2]:
    held_by = {c.install_id: c for c in held.computers} if held is not None else {}

    def extra(item: RosterInput) -> Dict[str, Any]:
        old = held_by.get(item.install_id)
        if source is not None:
            fallback = source.get(item.install_id, default_on)
        else:
            fallback = old.link_peers if old is not None else True
        kept = (link_peers or {}).get(item.install_id, fallback)
        return {"mesh": caps_mod.CAP_MESH in item.capabilities, "link_peers": bool(kept), "link_at": int(getattr(old, "link_at", 0)), "one_way": item.one_way,
                "may_receive_logins": item.may_receive_logins, "capabilities": sorted(set(item.capabilities))[:MAX_CAPS], "laptop": item.laptop}

    return roster_doc.plan(held, inputs, alpha=alpha, home=home, eligible=eligible, order=order, limit=MAX_COMPUTERS_V2,
                           doc=RosterV2, entry=RosterComputerV2, extra=extra)


def bump_reason_v2(held: Optional[RosterV2], new: RosterV2) -> Optional[str]:
    reason = roster_doc.bump_reason(held, new)
    if reason is not None or held is None:
        return reason
    for old, now in zip(held.computers, new.computers):
        if any(getattr(old, f) != getattr(now, f) for f in _AUTHORITY):
            return "authority"
    return None


def interim_same(held: RosterV2, new: RosterV2) -> bool:
    return held.home == new.home and ([c.model_dump(exclude=_INTERIM_HINTS) for c in held.computers]
                                      == [c.model_dump(exclude=_INTERIM_HINTS) for c in new.computers])


def judge_v2(**kwargs: Any) -> Verdict:
    return roster_doc.judge(**kwargs, verify_fn=verify_v2, bump_fn=bump_reason_v2)


def with_capabilities(inputs: Sequence[RosterInput], own_id: str, own_caps: Sequence[str],
                      peer_caps: Callable[[str], Any]) -> List[RosterInput]:
    out = []
    for item in inputs:
        got = list(own_caps) if item.install_id == own_id else peer_caps(item.install_id)
        out.append(dataclasses.replace(item, capabilities=tuple(c for c in got if isinstance(c, str) and 0 < len(c) <= 64 and c.isprintable())) if isinstance(got, (list, tuple)) else item)
    return out


from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.machines import settings_sign
from src.core.pack.machines.settings_sign import Signature, Verdict
from src.core.pack.reconnect.config import valid_relay_id
from src.core.relay_identity.device_key import DeviceKey, unb64url

SIGN_PREFIX = b"carnivore pack roster v1\x00"
MAX_COMPUTERS = 16
MAX_ADDRESSES = 6
MAX_CERT_BYTES = 2048
HINT_REISSUE_SECONDS = 300.0
HELLO_ROSTER_BUDGET = 12000

caps_mod.register(caps_mod.CAP_ROSTER)

BUMP_REASONS = ("first", "alpha", "home", "membership", "order", "eligibility", "pins", "keys", "relay")
REASON_SAME_GENERATION = "same generation, different structure"


class RosterRefused(ValueError):
    pass


class RosterFull(RosterRefused):

    def __init__(self, count: int, limit: int, left_out: Sequence[str]) -> None:
        super().__init__(f"the pack is full: {count} computers, the limit is {limit}")
        self.count, self.limit, self.left_out = count, limit, tuple(left_out)


def max_computers() -> int:
    return 64 if caps_mod.mesh_on() else MAX_COMPUTERS


def _b64_der(value: str) -> bytes:
    try:
        der = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise RosterRefused("cert is not base64") from None
    if not 0 < len(der) <= MAX_CERT_BYTES:
        raise RosterRefused("cert has a bad size")
    return der


class RosterComputer(BaseModel):
    """One computer of the Pack. ``cert`` and ``next_cert`` are standard base64 of the link certificate DER (the pins)."""

    model_config = ConfigDict(extra="forbid")

    install_id: str = Field(min_length=1, max_length=64)
    label: str = Field(default="", max_length=80)
    fed_public_key: str
    cert: str
    next_cert: Optional[str] = None
    addresses: List[str] = Field(default_factory=list, max_length=MAX_ADDRESSES)
    link_port: Optional[int] = Field(default=None, ge=1, le=65535)
    relay_id: Optional[str] = None
    takeover_eligible: bool = False

    @field_validator("fed_public_key")
    @classmethod
    def _fed_key(cls, value: str) -> str:
        if unb64url(value, 32) is None:
            raise ValueError("fed_public_key is not a 32 byte base64url key")
        return value

    @field_validator("cert")
    @classmethod
    def _cert(cls, value: str) -> str:
        _b64_der(value)
        return value

    @field_validator("next_cert")
    @classmethod
    def _next_cert(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            _b64_der(value)
        return value

    @field_validator("addresses")
    @classmethod
    def _addresses(cls, value: List[str]) -> List[str]:
        if any(not (0 < len(a) <= 255 and a.isprintable()) for a in value):
            raise ValueError("an address is not short printable text")
        return value

    @field_validator("relay_id")
    @classmethod
    def _relay_id(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not valid_relay_id(value):
            raise ValueError("relay_id is not a relay device id")
        return value

    def shas(self) -> Tuple[str, ...]:
        return tuple(hashlib.sha256(_b64_der(c)).hexdigest() for c in (self.cert, self.next_cert) if c)

    def ders(self) -> List[bytes]:
        return [_b64_der(c) for c in (self.cert, self.next_cert) if c]


class Roster(BaseModel):
    """The document. ``computers`` is in successor (rank) order."""

    model_config = ConfigDict(extra="forbid")

    generation: int = Field(ge=0)
    alpha: str = Field(min_length=1, max_length=64)
    home: str = Field(min_length=1, max_length=64)
    issued_at: int = Field(ge=0)
    computers: List[RosterComputer] = Field(min_length=1, max_length=MAX_COMPUTERS)

    @model_validator(mode="after")
    def _consistent(self) -> "Roster":
        ids = [c.install_id for c in self.computers]
        if len(set(ids)) != len(ids):
            raise ValueError("a computer is listed twice")
        if self.alpha not in ids:
            raise ValueError("the alpha is not in the roster")
        return self

    def entry(self, install_id: str) -> Optional[RosterComputer]:
        return next((c for c in self.computers if c.install_id == install_id), None)

    def order(self) -> List[str]:
        return [c.install_id for c in self.computers]


@dataclass(frozen=True)
class RosterInput:

    install_id: str
    label: str
    fed_public_key: str
    cert: bytes
    next_cert: Optional[bytes]
    addresses: Tuple[str, ...]
    link_port: Optional[int]
    relay_id: Optional[str]
    laptop: bool = False
    joined_at: str = ""
    capabilities: Tuple[str, ...] = ()
    one_way: bool = False
    may_receive_logins: bool = False


def canonical_bytes(roster: Roster) -> bytes:
    body = json.dumps(roster.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return SIGN_PREFIX + body.encode("ascii")


def sign(roster: Roster, key: DeviceKey, signer: str) -> Signature:
    return Signature(signer, key.sign(canonical_bytes(roster)))


def verify(roster: Roster, signature: Signature, public_key_b64: str) -> bool:
    return settings_sign.verify_bytes(canonical_bytes(roster), signature, public_key_b64)


def to_wire(roster: Roster, signature: Dict[str, Any]) -> Dict[str, Any]:
    return {"roster": roster.model_dump(mode="json"), "sig": signature}


def from_wire(raw: Any) -> Optional[Tuple[Roster, Optional[Signature]]]:
    if not isinstance(raw, dict) or not isinstance(raw.get("roster"), dict):
        return None
    try:
        return Roster(**raw["roster"]), settings_sign.signature_from(raw.get("sig"))
    except (TypeError, ValueError):
        return None


def fit_hello(extras: Dict[str, Any]) -> Dict[str, Any]:
    if len(json.dumps(extras, separators=(",", ":"))) > HELLO_ROSTER_BUDGET:
        return {k: v for k, v in extras.items() if k != "roster"}
    return extras


def _default_key(item: RosterInput) -> Tuple[bool, str, str]:
    return (item.laptop, item.joined_at, item.install_id)


def plan(held: Optional[Roster], inputs: Sequence[RosterInput], *, alpha: str, home: Optional[str] = None,
         eligible: Optional[Dict[str, bool]] = None, order: Optional[Sequence[str]] = None,
         limit: int = MAX_COMPUTERS, doc: Any = Roster, entry: Any = RosterComputer,
         extra: Optional[Callable[[RosterInput], Dict[str, Any]]] = None) -> Optional[Roster]:
    by_id = {i.install_id: i for i in inputs}
    if alpha not in by_id:
        return None
    ranked: List[str] = [i for i in (order if order is not None else (held.order() if held is not None else [])) if i in by_id]
    ranked += [i.install_id for i in sorted(by_id.values(), key=_default_key) if i.install_id not in ranked]
    if len(ranked) > limit:
        raise RosterFull(len(ranked), limit, ranked[limit:])
    if alpha not in ranked:
        return None
    flags = {c.install_id: c.takeover_eligible for c in held.computers} if held is not None else {}
    flags.update(eligible or {})
    computers = []
    for iid in ranked:
        item, on = by_id[iid], bool(flags.get(iid, False))
        computers.append(entry(
            **(extra(item) if extra is not None else {}),
            install_id=iid, label=item.label[:80], fed_public_key=item.fed_public_key,
            cert=base64.b64encode(item.cert).decode(), next_cert=base64.b64encode(item.next_cert).decode() if item.next_cert else None,
            addresses=list(item.addresses)[:MAX_ADDRESSES], link_port=item.link_port,
            relay_id=item.relay_id if (iid == alpha or on) else None, takeover_eligible=on))
    return doc(generation=held.generation if held is not None else 0, alpha=alpha,
                  home=home or (held.home if held is not None else alpha), issued_at=0, computers=computers)


def bump_reason(held: Optional[Roster], new: Roster) -> Optional[str]:
    if held is None:
        return "first"
    if held.alpha != new.alpha:
        return "alpha"
    if held.home != new.home:
        return "home"
    if set(held.order()) != set(new.order()):
        return "membership"
    if held.order() != new.order():
        return "order"
    for old, now in zip(held.computers, new.computers):
        if old.takeover_eligible != now.takeover_eligible:
            return "eligibility"
        if (old.cert, old.next_cert) != (now.cert, now.next_cert):
            return "pins"
        if old.fed_public_key != now.fed_public_key:
            return "keys"
        walked = now.install_id == new.alpha or now.takeover_eligible or old.takeover_eligible
        if walked and old.relay_id != now.relay_id:
            return "relay"
    return None


def hints_changed(held: Roster, new: Roster) -> bool:
    return held.model_dump(exclude={"generation", "issued_at"}) != new.model_dump(exclude={"generation", "issued_at"})


def judge(*, held: Optional[Roster], remote: Roster, signature: Optional[Signature], held_alpha: str,
          held_roster_alpha: Optional[str] = None, held_generation: Optional[int] = None,
          public_key_for: Callable[[str], Optional[str]], verify_fn: Callable[..., bool] = verify,
          bump_fn: Callable[..., Optional[str]] = bump_reason) -> Verdict:
    if signature is None:
        return Verdict(settings_sign.REFUSE_UNSIGNED, "a roster is always signed")
    handover = (signature.signer == held_roster_alpha and remote.alpha == held_alpha and held_alpha != signature.signer
                and (held_generation is None or remote.generation <= held_generation))
    if signature.signer != held_alpha and not handover:
        return Verdict(settings_sign.REFUSE_NOT_ALPHA, "signer is not the alpha held here")
    if held is not None:
        if (remote.generation, remote.issued_at) <= (held.generation, held.issued_at):
            return Verdict(settings_sign.IGNORE, settings_sign.REASON_NOT_NEWER)
        if remote.generation == held.generation and bump_fn(held, remote) is not None:
            return Verdict(settings_sign.REFUSE_MALFORMED, REASON_SAME_GENERATION)
        if remote.home != held.home and signature.signer != held.home:
            return Verdict(settings_sign.REFUSE_MALFORMED, "home changed by a signer that is not the home")
    elif remote.home != signature.signer:
        return Verdict(settings_sign.REFUSE_MALFORMED, "the first roster names its signer home")
    public_key = public_key_for(signature.signer)
    if public_key is None:
        return Verdict(settings_sign.REFUSE_UNPINNED, "signer is not paired here")
    if not verify_fn(remote, signature, public_key):
        return Verdict(settings_sign.REFUSE_BAD_SIGNATURE, "signature does not verify")
    return Verdict(settings_sign.ACCEPT)

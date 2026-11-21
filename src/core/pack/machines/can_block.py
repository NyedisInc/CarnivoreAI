
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Literal, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from src.core.pack.errors.input_error import PackInputError

log = structlog.get_logger(__name__)

BLOCK_VERSION = 1
MAX_LABELS = 16
MAX_GPUS = 4
MAX_BLOCK_BYTES = 3 * 1024
TOOL_NAMES = ("python3.12", "python3", "node", "npm", "git", "gh", "docker", "tmux", "claude", "playwright",
              "ffmpeg", "ffprobe", "codex", "blender", "brew")
VOCAB = frozenset(TOOL_NAMES) | {"playwright_browsers"}
LABEL_RE = re.compile(r"[a-z0-9][a-z0-9 ._-]{0,31}")
_VERSION_RE = r"^[0-9][0-9A-Za-z.+_-]{0,63}$"


def clean_labels(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        raise PackInputError("labels must be a list")
    out: List[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise PackInputError("a label must be text")
        label = item.strip().lower()
        if not LABEL_RE.fullmatch(label):
            raise PackInputError(f"bad label: {item[:40]!r} (a-z, 0-9, space, dot, dash, underscore; 1 to 32 characters)")
        if label not in out:
            out.append(label)
    if len(out) > MAX_LABELS:
        raise PackInputError(f"at most {MAX_LABELS} labels")
    return out


class Gpu(BaseModel):
    """One GPU as published: vendor word, model (64 chars), memory in GB (None for Apple's shared memory), discrete flag."""

    model_config = ConfigDict(extra="ignore", strict=True)
    vendor: Literal["apple", "nvidia", "amd", "intel"]
    model: str = Field(max_length=64)
    vram_gb: Optional[float] = Field(default=None, ge=0, le=65536, allow_inf_nan=False)
    discrete: bool


class CanBlock(BaseModel):
    """The strict receiver model of a ``can`` block (``parse`` is the entry point)."""

    model_config = ConfigDict(extra="ignore", strict=True)
    v: int = Field(ge=1, le=1_000_000)
    rev: str = Field(pattern=r"^[0-9a-f]{16}$")
    probed_at: float = Field(ge=0, allow_inf_nan=False)
    os: str = Field(pattern=r"^[a-z]{1,16}$")
    os_version: Optional[str] = Field(default=None, pattern=_VERSION_RE)
    arch: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_]{1,16}$")
    chip: Optional[str] = Field(default=None, max_length=64)
    cores: Optional[int] = Field(default=None, ge=1, le=4096)
    mem_gb: Optional[float] = Field(default=None, ge=0, le=65536, allow_inf_nan=False)
    gpus: List[Gpu] = Field(default_factory=list, max_length=MAX_GPUS)
    tools: Dict[str, bool] = Field(default_factory=dict)
    xcode: Optional[str] = Field(default=None, pattern=_VERSION_RE)
    ios_sim: bool = False
    brew: bool = False
    labels: List[str] = Field(default_factory=list, max_length=MAX_LABELS)
    installing: Optional[str] = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._+@-]{0,31}$")

    @field_validator("tools", mode="before")
    @classmethod
    def _known_tools(cls, value: Any) -> Any:
        return {k: v for k, v in value.items() if k in VOCAB} if isinstance(value, dict) else value

    @field_validator("labels")
    @classmethod
    def _label_shape(cls, value: List[str]) -> List[str]:
        if not all(LABEL_RE.fullmatch(label) for label in value):
            raise PackInputError("bad label")
        return value


def _digest(body: Dict[str, Any]) -> str:
    rest = {k: v for k, v in body.items() if k not in ("rev", "probed_at")}
    return hashlib.sha256(json.dumps(rest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def build(probe: Dict[str, Any], labels: List[str], installing: Optional[str]) -> Dict[str, Any]:
    try:
        good = clean_labels(list(labels))
    except ValueError as exc:
        log.warning("pack_can_labels_invalid", error=str(exc)[:80])
        good = [x for x in (str(i).strip().lower() for i in labels if isinstance(i, str)) if LABEL_RE.fullmatch(x)][:MAX_LABELS]
    tools = {k: bool(v) for k, v in (probe.get("tools") or {}).items() if k in VOCAB}
    body: Dict[str, Any] = {
        "v": BLOCK_VERSION, "probed_at": float(probe.get("probed_at") or 0), "os": probe.get("os"), "os_version": probe.get("os_version") or None,
        "arch": probe.get("arch") or None, "chip": (probe.get("chip") or "")[:64] or None, "cores": probe.get("cores"), "mem_gb": probe.get("mem_gb"),
        "gpus": list(probe.get("gpus") or [])[:MAX_GPUS], "tools": tools, "xcode": probe.get("xcode"),
        "ios_sim": bool(probe.get("ios_sim")), "brew": bool(probe.get("brew")), "labels": good, "installing": installing}
    body["rev"] = _digest(body)
    if parse(body) is None:
        log.warning("pack_can_block_self_invalid")
    return body


def parse(raw: Any) -> Optional[CanBlock]:
    if not isinstance(raw, dict):
        return None
    try:
        return CanBlock.model_validate(raw)
    except ValidationError as exc:
        log.info("pack_can_block_invalid", errors=len(exc.errors()))
        return None


_MEM_WORDS = ("normal", "warn", "critical")


class _Held(BaseModel):
    """Cores and memory set aside for picked jobs: finite, never negative."""

    model_config = ConfigDict(extra="ignore", strict=True)
    cpu: float = Field(default=0.0, ge=0, le=65536, allow_inf_nan=False)
    ram_gb: float = Field(default=0.0, ge=0, le=65536, allow_inf_nan=False)
    n: int = Field(default=0, ge=0, le=100000)


class PressureBlock(BaseModel):
    """The strict receiver model of a ``pressure`` block: a wrong type, a NaN or a free-text ``why`` voids the block."""

    model_config = ConfigDict(extra="ignore", strict=True)
    pegged: bool
    mem: Optional[Literal["normal", "warn", "critical"]] = None
    why: str = Field(default="", pattern=r"^[a-z0-9 .,;:%()_-]{0,160}$")
    since: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    busy_cores: Optional[float] = Field(default=None, ge=0, le=65536, allow_inf_nan=False)
    line: Optional[float] = Field(default=None, ge=0, le=65536, allow_inf_nan=False)
    cores: Optional[int] = Field(default=None, ge=0, le=4096)
    run_queue_per_core: Optional[float] = Field(default=None, ge=0, le=65536, allow_inf_nan=False)
    held: _Held = Field(default_factory=_Held)
    throttled: Optional[int] = Field(default=None, ge=0, le=100000)


def clean_received(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(snapshot)
    parsed = parse(out["can"]) if "can" in out else None
    if "can" in out:
        out["can"] = parsed.model_dump() if parsed is not None else None
    if "pressure" in out:
        try:
            out["pressure"] = PressureBlock.model_validate(out["pressure"]).model_dump() if isinstance(out["pressure"], dict) else None
        except ValidationError:
            log.info("pack_pressure_block_invalid")
            out["pressure"] = None
    return {k: v for k, v in out.items() if not (k in ("can", "pressure") and v is None)}

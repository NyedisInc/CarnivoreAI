
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

KIND_LIGHT = "light"
KIND_SESSION = "session"
KIND_AGENT = "agent"
KIND_TEST_SMALL = "test_small"
HEAVY_KINDS = ("browser", "suite", "build", "render")
DEFAULTS: Dict[str, tuple] = {
    KIND_LIGHT: (0.5, 0.5, 0.0),
    KIND_SESSION: (0.5, 0.8, 0.0),
    KIND_AGENT: (1.0, 1.5, 0.5),
    KIND_TEST_SMALL: (1.5, 1.0, 0.5),
    "browser": (2.0, 2.5, 1.0),
    "suite": (3.0, 2.0, 1.0),
    "build": (3.0, 2.0, 2.0),
    "render": (4.0, 4.0, 5.0),
}
DEFAULT_RUNTIME_S: Dict[str, float] = {
    KIND_LIGHT: 5.0,
    KIND_SESSION: 300.0,
    KIND_AGENT: 180.0,
    KIND_TEST_SMALL: 20.0,
    "browser": 60.0,
    "suite": 60.0,
    "build": 45.0,
    "render": 180.0,
}
_HINTS = (("browser", ("browser", "playwright", "e2e", "screenshot", "puppeteer")),
          ("render", ("render", "video", "transcode", "encode", "ffmpeg", "blender", "remotion")),
          ("suite", ("suite", "test", "pytest", "vitest", "jest", "validate")),
          ("build", ("build", "compile", "bundle", "docker", "package", "webpack", "tsc", "make", "xcodebuild", "gradle", "mvn")))
_TARGETED_TEST_RE = re.compile(r"(?:pytest|vitest|jest)\b[^\n;|&]*(?:\.py\b|\.test\.|\.spec\.|-k\s|::)|go\s+test\b[^\n;|&]*-run\s")


@dataclass(frozen=True)
class Workload:

    kind: str = KIND_LIGHT
    est_cpu_cores: float = 0.5
    est_ram_gb: float = 0.5
    est_disk_gb: float = 0.0

    @property
    def heavy(self) -> bool:
        return self.kind in HEAVY_KINDS or self.kind in (KIND_TEST_SMALL, KIND_AGENT)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def est_runtime_s(kind: str) -> float:
    return DEFAULT_RUNTIME_S.get(kind, 45.0)


def kind_from_task_type(task_type: Optional[str]) -> str:
    slug = (task_type or "").lower()
    for kind, words in _HINTS:
        if any(word in slug for word in words):
            return kind
    return KIND_LIGHT


def classify_command(command: str, *, requested_kind: Optional[str] = None) -> str:
    if requested_kind and requested_kind in DEFAULTS:
        if requested_kind == "suite" and _TARGETED_TEST_RE.search(command or ""):
            return KIND_TEST_SMALL
        return requested_kind
    inferred = kind_from_task_type(command)
    if inferred == "suite" and _TARGETED_TEST_RE.search(command or ""):
        return KIND_TEST_SMALL
    return inferred


def resolve(tag: Optional[Dict[str, Any]] = None, task_type: Optional[str] = None) -> Workload:
    tag = tag or {}
    kind = tag.get("kind") or kind_from_task_type(task_type)
    if kind not in DEFAULTS:
        raise ValueError(f"workload kind must be one of {', '.join(DEFAULTS)}")
    cpu, ram, disk = DEFAULTS[kind]
    figures = []
    for key, default in (("est_cpu_cores", cpu), ("est_ram_gb", ram), ("est_disk_gb", disk)):
        value = tag.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > 1024:
            raise ValueError(f"{key} must be a number from 0 to 1024")
        figures.append(float(value))
    return Workload(kind, *figures)

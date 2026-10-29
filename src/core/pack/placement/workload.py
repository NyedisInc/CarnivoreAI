
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

KIND_LIGHT = "light"
HEAVY_KINDS = ("browser", "suite", "build", "render")
DEFAULTS: Dict[str, tuple] = {KIND_LIGHT: (0.5, 0.6, 0.0), "browser": (2.0, 3.0, 1.0), "suite": (4.0, 4.0, 1.0),
                              "build": (4.0, 3.0, 3.0), "render": (6.0, 6.0, 5.0)}
_HINTS = (("browser", ("browser", "playwright", "e2e", "screenshot", "puppeteer")),
          ("render", ("render", "video", "transcode", "encode")),
          ("suite", ("suite", "test", "pytest", "vitest", "validate")),
          ("build", ("build", "compile", "bundle", "docker", "package")))


@dataclass(frozen=True)
class Workload:

    kind: str = KIND_LIGHT
    est_cpu_cores: float = 0.5
    est_ram_gb: float = 0.6
    est_disk_gb: float = 0.0

    @property
    def heavy(self) -> bool:
        return self.kind in HEAVY_KINDS

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def kind_from_task_type(task_type: Optional[str]) -> str:
    slug = (task_type or "").lower()
    for kind, words in _HINTS:
        if any(word in slug for word in words):
            return kind
    return KIND_LIGHT


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

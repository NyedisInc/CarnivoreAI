
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()

BOOT_MEASURED: str = "measured"
BOOT_CANNOT_DETERMINE: str = "cannot_determine"

CHANGE_REBOOTED: str = "rebooted"
CHANGE_SAME_BOOT: str = "same_boot"
CHANGE_FIRST_RECORD: str = "first_record"
CHANGE_CANNOT_DETERMINE: str = "cannot_determine"

BOOT_EPOCH_TOLERANCE_SECONDS: int = 2

SYSCTL_BIN: str = "/usr/sbin/sysctl"
PROC_STAT: Path = Path("/proc/stat")
PROBE_TIMEOUT_SECONDS: float = 5.0

_KERN_BOOTTIME_RE = re.compile(r"sec\s*=\s*(\d+)")
_BTIME_RE = re.compile(r"^btime\s+(\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class BootTime:

    outcome: str
    epoch: Optional[int] = None
    source: Optional[str] = None
    detail: str = ""

    @property
    def measured(self) -> bool:
        return self.outcome == BOOT_MEASURED and self.epoch is not None


def parse_kern_boottime(text: str) -> Optional[int]:
    match = _KERN_BOOTTIME_RE.search(text or "")
    return int(match.group(1)) if match else None


def parse_proc_stat_btime(text: str) -> Optional[int]:
    match = _BTIME_RE.search(text or "")
    return int(match.group(1)) if match else None


def read_boot_time() -> BootTime:
    try:
        proc = subprocess.run(
            [SYSCTL_BIN, "-n", "kern.boottime"],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
        if proc.returncode == 0:
            epoch = parse_kern_boottime(proc.stdout)
            if epoch:
                return BootTime(BOOT_MEASURED, epoch, "kern.boottime")
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("boot_time_sysctl_unavailable", error=str(exc))
    try:
        epoch = parse_proc_stat_btime(PROC_STAT.read_text())
        if epoch:
            return BootTime(BOOT_MEASURED, epoch, "proc_stat")
    except OSError as exc:
        logger.debug("boot_time_proc_stat_unavailable", error=str(exc))
    return BootTime(
        BOOT_CANNOT_DETERMINE,
        detail="neither kern.boottime nor /proc/stat answered",
    )


def compare_boots(previous_epoch: Optional[int], current: BootTime) -> str:
    if not current.measured:
        return CHANGE_CANNOT_DETERMINE
    if previous_epoch is None:
        return CHANGE_FIRST_RECORD
    if abs(int(current.epoch) - int(previous_epoch)) > BOOT_EPOCH_TOLERANCE_SECONDS:
        return CHANGE_REBOOTED
    return CHANGE_SAME_BOOT

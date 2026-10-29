
from __future__ import annotations

import os
import stat as stat_module
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Tuple

from src.core.test_write_guard import OutsideTempWriteError, assert_test_write_allowed

SWEEPABLE_BUCKET_NAMES: Tuple[str, str] = (".carnivore_uploads", ".cloude_uploads")

BUCKET_GITIGNORE = ".gitignore"


class SweepOutcome(Enum):

    SWEEP = "sweep"
    SKIP = "skip"
    REFUSED = "refused"


@dataclass(frozen=True)
class SweepVerdict:

    outcome: SweepOutcome
    bucket: Path | None
    reason: str


def sweep_verdicts(base: str | os.PathLike | None) -> list[SweepVerdict]:
    return [sweep_verdict(base, name) for name in SWEEPABLE_BUCKET_NAMES]


def sweep_verdict(base: str | os.PathLike | None, name: str) -> SweepVerdict:
    if name not in SWEEPABLE_BUCKET_NAMES:
        raise ValueError(f"{name!r} is not an upload bucket name")
    if base is None:
        return SweepVerdict(
            SweepOutcome.REFUSED, None,
            "base path is None; an undetermined base is refused, never "
            "resolved against the process working directory",
        )
    raw = os.fspath(base)
    if not isinstance(raw, str) or not raw.strip():
        return SweepVerdict(
            SweepOutcome.REFUSED, None,
            "base path is empty or blank; Path('').resolve() would "
            "silently become the process working directory",
        )

    try:
        resolved_base = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        return SweepVerdict(
            SweepOutcome.REFUSED, None,
            f"base path could not be resolved ({exc})",
        )

    if resolved_base == Path(resolved_base.anchor):
        return SweepVerdict(
            SweepOutcome.REFUSED, None,
            f"base path resolves to the filesystem root {resolved_base}; "
            "that is a misconfiguration, not a project",
        )

    bucket = resolved_base / name

    try:
        assert_test_write_allowed(bucket)
    except OutsideTempWriteError as exc:
        return SweepVerdict(SweepOutcome.REFUSED, None, str(exc))

    try:
        link_stat = os.lstat(bucket)
    except FileNotFoundError:
        return SweepVerdict(
            SweepOutcome.SKIP, None, "no uploads bucket beneath this base"
        )
    except OSError as exc:
        return SweepVerdict(
            SweepOutcome.REFUSED, None,
            f"could not stat {bucket} ({exc}); an unreadable target is "
            "refused, not assumed empty",
        )

    if stat_module.S_ISLNK(link_stat.st_mode):
        return SweepVerdict(
            SweepOutcome.REFUSED, None,
            f"{bucket} is a symlink. iterdir() and unlink() both follow "
            "it, so pruning would delete files outside the uploads leaf.",
        )
    if not stat_module.S_ISDIR(link_stat.st_mode):
        return SweepVerdict(
            SweepOutcome.SKIP, None,
            f"{bucket} exists but is not a directory; left untouched",
        )
    if resolved_base.name in SWEEPABLE_BUCKET_NAMES:
        return SweepVerdict(
            SweepOutcome.REFUSED, None,
            f"base {resolved_base} is itself an uploads "
            "directory; a nested uploads bucket is a misconfiguration",
        )
    try:
        real_bucket = Path(os.path.realpath(bucket))
    except OSError as exc:
        return SweepVerdict(
            SweepOutcome.REFUSED, None,
            f"could not resolve {bucket} ({exc})",
        )
    if real_bucket != bucket:
        return SweepVerdict(
            SweepOutcome.REFUSED, None,
            f"{bucket} really lives at {real_bucket}; the sweep target "
            "must be the path it claims to be",
        )

    return SweepVerdict(SweepOutcome.SWEEP, bucket, "")

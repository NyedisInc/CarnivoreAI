
from __future__ import annotations

import os
from pathlib import Path
from typing import Set

import structlog

from src.core.pack.jobs import gitio, paths

log = structlog.get_logger()
_JOB_PREFIXES = ("refs/heads/job-", "refs/heads/result-")


def ensure(jobs_root: Path, project_uid: str, toplevel: str) -> str:
    side = paths.side_repo_dir(jobs_root, project_uid)
    if not (side / "HEAD").exists():
        side.parent.mkdir(parents=True, exist_ok=True)
        gitio.run(["init", "--bare", "-q", str(side)])
    common = gitio.out(gitio.run(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=toplevel))
    wanted = os.path.join(common, "objects") + "\n"
    alt = side / "objects" / "info" / "alternates"
    if not alt.exists() or alt.read_text() != wanted:
        alt.parent.mkdir(parents=True, exist_ok=True)
        alt.write_text(wanted)
    return str(side)


def drop_ref(side: str, ref: str) -> None:
    gitio.run(["update-ref", "-d", ref], git_dir=side, check=False)


def prune(side: str, *, older_than_s: float, keep: Set[str], now: float) -> int:
    listing = gitio.out(gitio.run(["for-each-ref", "--format=%(refname) %(committerdate:unix)"], git_dir=side)).splitlines()
    dropped = 0
    for line in listing:
        ref, _, stamp = line.rpartition(" ")
        if not ref.startswith(_JOB_PREFIXES) or ref in keep or not stamp.isdigit():
            continue
        if now - int(stamp) > older_than_s:
            drop_ref(side, ref)
            dropped += 1
    gitio.run(["repack", "-a", "-d", "-l", "-q"], git_dir=side)
    gitio.run(["prune", "--expire=2.hours.ago"], git_dir=side)
    log.info("jobs_side_pruned", refs=dropped)
    return dropped

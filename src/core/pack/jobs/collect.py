
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import structlog

from src.core.pack.jobs import gitio, guards
from src.core.pack.jobs.types import Collected, JobError

log = structlog.get_logger()


def _exclude_spec(item: str) -> str:
    return item if item.startswith(":") else f":(exclude){item}"


def _unignored(items: Sequence[str], git) -> List[str]:
    plain = [e for e in items if not e.startswith(":")]
    if not plain:
        return list(items)
    ignored = set(git("check-ignore", "--stdin", "-z", input="".join(f"{e}\0" for e in plain).encode(), check=False).stdout.decode("utf-8", "surrogateescape").split("\0"))
    return [e for e in items if e not in ignored]


def _changes(raw: bytes) -> List[Tuple[str, Optional[str], Optional[str]]]:
    parts = raw.split(b"\0")
    out: List[Tuple[str, Optional[str], Optional[str]]] = []
    for i in range(0, len(parts) - 1, 2):
        meta = parts[i].decode().lstrip(":").split()
        zero = set("0")
        out.append((parts[i + 1].decode("utf-8", "surrogateescape"), None if set(meta[2]) == zero else meta[2],
                    None if set(meta[3]) == zero else meta[3]))
    return out


def collect(job_folder: str, snapshot_commit: str, outputs: Sequence[str], job_id: str, out_dir: Path, *,
            exclude: Sequence[str] = ()) -> Collected:
    def git(*args: str, check: bool = True, input: Optional[bytes] = None):
        return gitio.run(list(args), cwd=job_folder, check=check, input=input)

    git("add", "-A", "--", ".", *guards.exclude_pathspecs(), *[_exclude_spec(e) for e in _unignored(exclude, git)])
    for pattern in outputs:
        git("add", "-f", "--", f":(glob){pattern}", *guards.exclude_pathspecs(), check=False)
    tree = gitio.out(git("write-tree"))
    if tree == gitio.out(git("rev-parse", f"{snapshot_commit}^{{tree}}")):
        return Collected(snapshot_commit, 0, "")
    result = gitio.out(git("commit-tree", tree, "-p", snapshot_commit, "-m", f"job {job_id} result"))
    big = guards.oversize(_changes(git("diff-tree", "-r", "--no-renames", "-z", snapshot_commit, result).stdout), cwd=job_folder)
    if big:
        raise JobError("result_too_large", f"the result is too large to bring back: {big}")
    ref = f"refs/carnivore/jobs/{job_id}/result"
    git("update-ref", ref, result)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    bundle = str(Path(out_dir) / f"{job_id}-result.bundle")
    git("bundle", "create", bundle, ref, f"^{snapshot_commit}")
    names = [n for n in gitio.out(git("diff-tree", "-r", "--no-renames", "--name-only", snapshot_commit, result)).splitlines() if n]
    log.info("jobs_collected", job_id=job_id, changed=len(names))
    return Collected(result, len(names), bundle)


def drop_refs(repo_dir: str, job_id: str) -> None:
    names: List[str] = gitio.out(gitio.run(["for-each-ref", "--format=%(refname)", f"refs/carnivore/jobs/{job_id}/"], cwd=repo_dir)).splitlines()
    for name in names:
        gitio.run(["update-ref", "-d", name], cwd=repo_dir, check=False)

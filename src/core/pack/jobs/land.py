
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.pack.jobs import gitio, guards, snapshot
from src.core.pack.jobs.types import JobError, LandResult

log = structlog.get_logger()
Entry = Tuple[str, str]
_SHA = re.compile(r"^[0-9a-f]{40,64}$")


def _parse(raw: bytes) -> Dict[str, Tuple[str, Optional[Entry], Optional[Entry]]]:
    parts = raw.split(b"\0")
    found: Dict[str, Tuple[str, Optional[Entry], Optional[Entry]]] = {}
    for i in range(0, len(parts) - 1, 2):
        meta = parts[i].decode().lstrip(":").split()
        path = parts[i + 1].decode("utf-8", "surrogateescape")
        omode, nmode, osha, nsha, status = meta[0], meta[1], meta[2], meta[3], meta[4][0]
        found[path] = (status, None if status == "A" else (omode, osha), None if status == "D" else (nmode, nsha))
    return found


def _safe(rel: str, root_real: str) -> str:
    parts = rel.split("/")
    if rel.startswith("/") or any(p in ("", ".", "..") or p.casefold() == ".git" or guards.is_dep_name(p) for p in parts):
        raise JobError("unsafe_path", "the result holds a path outside the folder")
    dest = os.path.join(root_real, *parts)
    parent = os.path.realpath(os.path.dirname(dest))
    if parent != root_real and not parent.startswith(root_real + os.sep):
        raise JobError("unsafe_path", "the result path leaves the folder through a link")
    if any(p.casefold() == ".git" or guards.is_dep_name(p) for p in os.path.relpath(parent, root_real).split(os.sep)):
        raise JobError("unsafe_path", "the result path reaches a git or dependency folder through a link")
    return dest


def _through_link(root_real: str, rels: Sequence[str]) -> Optional[str]:
    for rel in rels:
        parts = rel.split("/")
        for i in range(1, len(parts)):
            step = "/".join(parts[:i])
            try:
                st = os.lstat(os.path.join(root_real, step))
            except (FileNotFoundError, NotADirectoryError):
                break
            if stat.S_ISLNK(st.st_mode):
                return step
    return None


def _caller_entry(side: str, toplevel: str, rel: str) -> Optional[Entry]:
    path = os.path.join(toplevel, rel)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except NotADirectoryError:
        return ("040000", "")
    if stat.S_ISLNK(st.st_mode):
        body, mode = os.readlink(path).encode("utf-8", "surrogateescape"), "120000"
    elif stat.S_ISREG(st.st_mode):
        with open(path, "rb") as fh:
            body = fh.read()
        mode = "100755" if st.st_mode & 0o111 else "100644"
    else:
        return ("040000", "")
    cp = gitio.run(["hash-object", f"--path={rel}", "--stdin"], git_dir=side, work_tree=toplevel, input=body)
    return (mode, gitio.out(cp))


def _is_stale_output(rel: str, path: str, outputs: Sequence[str], snapshot_at: float) -> bool:
    hit = any(fnmatch.fnmatch(rel, p) or ("/" not in p and fnmatch.fnmatch(os.path.basename(rel), p)) for p in outputs)
    try:
        return hit and os.lstat(path).st_mtime < snapshot_at
    except OSError:
        return False


def _clashes(side: str, toplevel: str, changes: dict, outputs: Sequence[str], snapshot_at: float) -> List[str]:
    bad: List[str] = []
    for rel, (_status, snap, result) in changes.items():
        now = _caller_entry(side, toplevel, rel)
        if now == result:
            continue
        if snap is not None:
            if now != snap:
                bad.append(rel)
        elif now is not None and not _is_stale_output(rel, os.path.join(toplevel, rel), outputs, snapshot_at):
            bad.append(rel)
    return sorted(bad)


def _sidecar(dest: str, kind: str) -> str:
    return os.path.join(os.path.dirname(dest), f".{os.path.basename(dest)}{guards.LAND_TEMP_MARK}{kind}")


def _restore_leftovers(toplevel: str, rels: Sequence[str], result: Dict[str, Optional[Entry]], side: str) -> None:
    for rel in rels:
        dest = os.path.join(toplevel, rel)
        tmp, bak = _sidecar(dest, "tmp"), _sidecar(dest, "bak")
        if os.path.lexists(tmp):
            os.unlink(tmp)
        if not os.path.lexists(bak):
            continue
        if not os.path.lexists(dest):
            os.replace(bak, dest)
        elif _caller_entry(side, toplevel, rel) == result.get(rel):
            os.unlink(bak)
        else:
            n = 1
            while os.path.lexists(f"{bak}.{n}"):
                n += 1
            os.replace(bak, f"{bak}.{n}")
            log.warning("jobs_land_backup_kept", path=rel, kept_as=f"{bak}.{n}")


def _apply(toplevel: str, staged: str, writes: List[str], removes: List[str]) -> None:
    made_dirs: List[str] = []
    moved: List[Tuple[str, str]] = []
    fresh: List[str] = []
    tmps: List[Tuple[str, str]] = []
    try:
        for rel in writes:
            dest, src = os.path.join(toplevel, rel), os.path.join(staged, rel)
            parent = os.path.dirname(dest)
            missing = []
            while not os.path.isdir(parent):
                missing.append(parent)
                parent = os.path.dirname(parent)
            for d in reversed(missing):
                os.mkdir(d)
                made_dirs.append(d)
            tmp = _sidecar(dest, "tmp")
            if os.path.lexists(tmp):
                os.unlink(tmp)
            if os.path.islink(src):
                os.symlink(os.readlink(src), tmp)
            else:
                shutil.copy2(src, tmp)
            tmps.append((tmp, dest))
        for rel in removes:
            dest = os.path.join(toplevel, rel)
            if os.path.lexists(dest):
                backup = _sidecar(dest, "bak")
                os.replace(dest, backup)
                moved.append((dest, backup))
        for tmp, dest in tmps:
            if os.path.lexists(dest):
                backup = _sidecar(dest, "bak")
                os.replace(dest, backup)
                moved.append((dest, backup))
            else:
                fresh.append(dest)
            os.replace(tmp, dest)
    except OSError as exc:
        for tmp, _dest in tmps:
            if os.path.lexists(tmp):
                os.unlink(tmp)
        for dest in fresh:
            if os.path.lexists(dest):
                os.unlink(dest)
        for dest, backup in reversed(moved):
            if os.path.lexists(dest):
                os.unlink(dest)
            os.replace(backup, dest)
        for d in reversed(made_dirs):
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        raise JobError("land_failed", "the result could not be written into the folder, nothing was changed") from exc
    for _dest, backup in moved:
        if os.path.lexists(backup):
            os.unlink(backup)


def land(toplevel: str, side_git_dir: str, snapshot_commit: str, result_commit: str, job_id: str, *,
         outputs: Sequence[str] = (), snapshot_at: float, skip: Sequence[str] = ()) -> LandResult:
    if not (_SHA.match(snapshot_commit) and _SHA.match(result_commit)):
        raise JobError("bad_commit", "the result is not named by a full commit id")
    raw = gitio.run(["diff-tree", "-r", "--no-renames", "-z", snapshot_commit, result_commit], git_dir=side_git_dir).stdout
    changes = _parse(raw)
    names, parents = snapshot.blocked_names(skip)
    dropped = sorted(r for r in changes if r.casefold() in names or r.casefold() in parents)
    changes = {r: c for r, c in changes.items() if r not in dropped}
    root_real = os.path.realpath(toplevel)
    linked = snapshot.harness_link(root_real, skip) if skip else None
    if linked:
        clashes, too_big = [f"{linked} is a link on this computer now, so the result is parked"], None
    else:
        for rel in changes:
            _safe(rel, root_real)
        through = _through_link(root_real, sorted(changes))
        if through:
            clashes, too_big = [f"the result writes through a link on this computer: {through}"], None
        else:
            _restore_leftovers(root_real, sorted(changes), {r: new for r, (_s, _o, new) in changes.items()}, side_git_dir)
            clashes = _clashes(side_git_dir, toplevel, changes, outputs, snapshot_at)
            too_big = None if clashes else guards.oversize(
                ((r, o[1] if o else None, n[1] if n else None) for r, (_s, o, n) in changes.items()), git_dir=side_git_dir)
    if too_big:
        log.warning("jobs_land_too_large", job_id=job_id, why=too_big)
        clashes = [too_big]
    if clashes:
        ref = f"refs/carnivore/jobs/{job_id}"
        gitio.run(["fetch", "--no-tags", "--no-write-fetch-head", side_git_dir, f"+refs/heads/result-{job_id}:{ref}"], cwd=toplevel, timeout=600.0)
        log.info("jobs_land_clash", job_id=job_id, clashes=len(clashes))
        return LandResult(clashes=clashes, ref=ref, dropped=dropped)
    writes = sorted(r for r, (_s, _o, new) in changes.items() if new is not None)
    removes = sorted(r for r, (_s, _o, new) in changes.items() if new is None)
    with tempfile.TemporaryDirectory(prefix="carn-land-") as scratch:
        index = os.path.join(scratch, "index")
        staged = os.path.join(scratch, "tree") + os.sep
        env = {"GIT_INDEX_FILE": index}
        gitio.run(["read-tree", result_commit], git_dir=side_git_dir, work_tree=toplevel, env=env)
        if writes:
            gitio.run(["checkout-index", "-f", "-z", f"--prefix={staged}", "--stdin"], git_dir=side_git_dir, work_tree=toplevel,
                      env=env, input=b"".join(w.encode("utf-8", "surrogateescape") + b"\0" for w in writes))
        _apply(root_real, staged, writes, removes)
    log.info("jobs_landed", job_id=job_id, applied=len(writes), deleted=len(removes))
    return LandResult(applied=writes, deleted=removes, dropped=dropped)

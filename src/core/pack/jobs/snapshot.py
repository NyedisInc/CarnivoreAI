
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import structlog

from src.core.pack.jobs import gitio, guards, side_repo
from src.core.pack.jobs.types import DepDir, JobError, Snapshot

log = structlog.get_logger()
_LOCK_GLOBS = (":(glob)**/package-lock.json", ":(glob)**/requirements*.txt")
_REQ = re.compile(r"^requirements.*\.txt$")
HARNESS_CONFIG_PATHS = (
    ".claude/settings.json", ".claude/settings.local.json", ".mcp.json", ".codex/config.toml",
    ".agents/hooks.json", ".agent/hooks.json", "_agents/hooks.json", "_agent/hooks.json",
)


def harness_paths(scope: str) -> List[str]:
    parts = [p for p in scope.split("/") if p]
    levels = [""] + ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    return list(dict.fromkeys(f"{lv}/{p}" if lv else p for lv in levels for p in HARNESS_CONFIG_PATHS))


def blocked_names(paths: Sequence[str]) -> Tuple[set, set]:
    names = {p.casefold() for p in paths}
    return names, {"/".join(n.split("/")[:i]) for n in names for i in range(1, len(n.split("/")))}


def harness_link(toplevel: str, paths: Sequence[str], entries: Iterable[Tuple[str, str]] = ()) -> Optional[str]:
    risky = {p.casefold() for m, p in entries if m in ("120000", "160000")}
    for path in paths:
        parts = path.split("/")
        steps = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
        for step in steps:
            if step.casefold() in risky:
                return step
        for i, step in enumerate(steps):
            try:
                st = os.lstat(os.path.join(toplevel, step))
            except OSError:
                break
            if i < len(steps) - 1:
                if not stat.S_ISDIR(st.st_mode):
                    return step
            elif not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                return step
    return None


def _listing(raw: bytes, staged: bool) -> List[Tuple[str, str, str]]:
    out = []
    for rec in raw.split(b"\0"):
        meta, _, name = rec.partition(b"\t")
        f = meta.decode().split()
        if len(f) >= 3:
            out.append((f[0], f[1] if staged else f[2], name.decode("utf-8", "surrogateescape")))
    return out


def _pin_harness_config(git: Callable[..., "subprocess.CompletedProcess[bytes]"], head: Optional[str], scope: str) -> None:
    names, parents = blocked_names(harness_paths(scope))
    hit = lambda rel: rel.casefold() in names or rel.casefold() in parents
    for _mode, _sha, rel in _listing(git("ls-files", "-s", "-z").stdout, True):
        if hit(rel):
            git("update-index", "--force-remove", "--", rel)
    old = _listing(git("ls-tree", "-r", "-z", head, check=False).stdout, False) if head else []
    for mode, sha, rel in old:
        if hit(rel):
            git("update-index", "--add", "--cacheinfo", f"{mode},{sha},{rel}")


def _nul(cp: "subprocess.CompletedProcess[bytes]") -> List[str]:
    return [p.decode("utf-8", "surrogateescape") for p in cp.stdout.split(b"\0") if p]


def _store_bytes(side: str) -> int:
    total = 0
    for line in gitio.out(gitio.run(["count-objects", "-v"], git_dir=side)).splitlines():
        key, _, value = line.partition(":")
        if key in ("size", "size-pack") and value.strip().isdigit():
            total += int(value) * 1024
    return total


def _file_size(path: str) -> int:
    try:
        return os.lstat(path).st_size
    except OSError:
        return 0


def _py_version(venv_dir: str) -> Optional[str]:
    try:
        cp = subprocess.run([os.path.join(venv_dir, "bin", "python"), "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                            capture_output=True, timeout=10, shell=False)
    except (OSError, subprocess.SubprocessError):
        return None
    text = cp.stdout.decode().strip()
    return text if cp.returncode == 0 and re.match(r"^\d+\.\d+$", text) else None


def _sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _dep_dirs(base: str, lockfiles: Sequence[str], lock_bases: Sequence[str], seen: Dict[str, DepDir]) -> None:
    by_dir: Dict[str, List[str]] = {}
    for rel in lockfiles:
        by_dir.setdefault(os.path.dirname(rel), []).append(rel)
    for folder, files in sorted(by_dir.items()):
        def locks(match: Callable[[str], bool]) -> Dict[str, str]:
            found: Dict[str, str] = {}
            for rel in files:
                if match(os.path.basename(rel)):
                    for lb in lock_bases:
                        if os.path.isfile(os.path.join(lb, rel)):
                            found[rel] = _sha(os.path.join(lb, rel))
                            break
            return found
        npm = locks(lambda n: n == "package-lock.json")
        node = os.path.join(folder, "node_modules")
        if npm and node not in seen and os.path.isdir(os.path.join(base, node)):
            seen[node] = DepDir(node, "npm", npm, None)
        reqs = locks(lambda n: bool(_REQ.match(n)))
        for name in (".venv", "venv"):
            venv = os.path.join(folder, name)
            if reqs and venv not in seen and os.path.isdir(os.path.join(base, venv)):
                seen[venv] = DepDir(venv, "venv", reqs, _py_version(os.path.join(base, venv)))


def _lockfiles(cwd: str, env: Optional[Dict[str, str]], git_dir: Optional[str], work_tree: Optional[str]) -> List[str]:
    cp = gitio.run(["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *_LOCK_GLOBS],
                   git_dir=git_dir, work_tree=work_tree, cwd=cwd, env=env, check=False)
    return _nul(cp)


def dep_dirs_of(root: str) -> List[DepDir]:
    deps: Dict[str, DepDir] = {}
    _dep_dirs(root, _lockfiles(root, None, None, None), [root], deps)
    return list(deps.values())


def _outside_links(toplevel: str, scope: str) -> List[str]:
    real_top = os.path.realpath(toplevel)
    found: List[str] = []
    for root, dirs, files in os.walk(os.path.join(toplevel, scope) if scope else toplevel):
        dirs[:] = [d for d in dirs if d != ".git" and d not in guards.DEP_DIR_NAMES]
        for name in dirs + files:
            full = os.path.join(root, name)
            if os.path.islink(full):
                target = os.path.realpath(full)
                if target != real_top and not target.startswith(real_top + os.sep):
                    found.append(os.path.relpath(full, toplevel))
    return sorted(found)


def _untracked(toplevel: str, scope: str, env: Dict[str, str], git_dir: str, notes: List[str]) -> Tuple[List[str], int]:
    spec = [f":(literal){scope}" if scope else ".", *guards.exclude_pathspecs()]
    names = _nul(gitio.run(["ls-files", "-z", "--others", "--exclude-standard", "--", *spec],
                           git_dir=git_dir, work_tree=toplevel, cwd=toplevel, env=env))
    dep_hits = _nul(gitio.run(["ls-files", "-z", "--others", "--exclude-standard", "--directory", "--",
                               *[f":(glob)**/{n}/" for n in sorted(guards.DEP_DIR_NAMES)]],
                              git_dir=git_dir, work_tree=toplevel, cwd=toplevel, env=env))
    for folder in dep_hits:
        if not folder.rstrip("/").endswith("__pycache__"):
            notes.append(f"left out {folder.rstrip('/')}: dependency folder, rebuilt on the other computer")
    keep: List[str] = []
    total = 0
    for rel in names:
        why = guards.skip_reason(rel, os.path.join(toplevel, rel))
        if why:
            notes.append(f"left out {rel.rstrip('/')}: {why}")
            continue
        keep.append(rel)
        total += _file_size(os.path.join(toplevel, rel))
    return keep, total


def take(folder: str, project_uid: str, job_id: str, *, jobs_root: Path, carry: Sequence[str] = (),
         clock: Callable[[], float] = time.time, project_root: Optional[str] = None, agent: bool = False,
         commit_ref: Optional[str] = None) -> Snapshot:
    top_cp = gitio.run(["rev-parse", "--show-toplevel"], cwd=folder, check=False)
    if top_cp.returncode != 0:
        raise JobError("not_a_repo", "the folder is not inside a git work tree")
    toplevel = os.path.realpath(gitio.out(top_cp))
    scope = os.path.relpath(os.path.realpath(folder), toplevel)
    scope = "" if scope == "." else scope
    git_dir = gitio.out(gitio.run(["rev-parse", "--absolute-git-dir"], cwd=toplevel))
    common = gitio.out(gitio.run(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=toplevel))
    index = gitio.out(gitio.run(["rev-parse", "--path-format=absolute", "--git-path", "index"], cwd=toplevel))
    head_cp = gitio.run(["rev-parse", "--verify", "-q", "HEAD"], cwd=toplevel, check=False)
    head = gitio.out(head_cp) if head_cp.returncode == 0 else None
    if agent:
        listed = _listing(gitio.run(["ls-files", "-s", "-z"], cwd=toplevel).stdout, True)
        listed += _listing(gitio.run(["ls-tree", "-r", "-z", head], cwd=toplevel).stdout, False) if head else []
        linked = harness_link(toplevel, harness_paths(scope), [(m, p) for m, _s, p in listed])
        if linked:
            raise JobError("harness_linked", f"{linked} sits behind a link, and an agent job cannot carry settings that sit behind a link, "
                           "so the task stays on this computer")
    side = side_repo.ensure(jobs_root, project_uid, toplevel)
    before = _store_bytes(side)
    notes: List[str] = []
    tmp = tempfile.mkdtemp(prefix="cvjob-snap-")
    try:
        temp_index = os.path.join(tmp, "index")
        env = {"GIT_INDEX_FILE": temp_index, "GIT_OBJECT_DIRECTORY": os.path.join(side, "objects"),
               "GIT_ALTERNATE_OBJECT_DIRECTORIES": os.path.join(common, "objects")}
        if os.path.exists(index):
            shutil.copyfile(index, temp_index)
        elif head:
            gitio.run(["read-tree", head], git_dir=git_dir, work_tree=toplevel, cwd=toplevel, env=env)

        def git(*args: str, check: bool = True, input: Optional[bytes] = None):
            return gitio.run(list(args), git_dir=git_dir, work_tree=toplevel, cwd=toplevel, env=env, check=check, input=input)

        untracked: List[str] = []
        if commit_ref is not None:
            if git("cat-file", "-e", f"{commit_ref}^{{commit}}", check=False).returncode != 0:
                raise JobError("bad_request", "that commit is not in the project's repository", 422)
            tree = gitio.out(git("rev-parse", f"{commit_ref}^{{tree}}"))
        else:
            scope_spec = f":(literal){scope}" if scope else "."
            modified = _nul(git("diff-files", "--name-only", "-z", "--", scope_spec))
            untracked, untracked_bytes = _untracked(toplevel, scope, env, git_dir, notes)
            total = untracked_bytes + sum(_file_size(os.path.join(toplevel, m)) for m in modified)
            if len(untracked) > guards.MAX_UNTRACKED_FILES or total > guards.MAX_SNAPSHOT_BYTES:
                raise JobError("snapshot_too_large", f"{len(untracked)} new files and {total // (1024 * 1024)} MiB are over the limit "
                               f"({guards.MAX_UNTRACKED_FILES} files, {guards.MAX_SNAPSHOT_BYTES // 1024 ** 3} GiB)")
            git("add", "-u", "--", scope_spec)
            if untracked:
                listing = os.path.join(tmp, "paths")
                Path(listing).write_bytes(b"\0".join(f":(literal){u}".encode("utf-8", "surrogateescape") for u in untracked) + b"\0")
                git("add", f"--pathspec-from-file={listing}", "--pathspec-file-nul")
            for pattern in carry:
                forced = _nul(git("ls-files", "-z", "-o", "-i", "--exclude-standard", "--", pattern, *guards.exclude_pathspecs(), check=False))
                total += sum(_file_size(os.path.join(toplevel, f)) for f in forced)
                if len(forced) > guards.MAX_UNTRACKED_FILES or total > guards.MAX_SNAPSHOT_BYTES:
                    raise JobError("snapshot_too_large", f"carry pattern {pattern} brings in too much ({total // (1024 * 1024)} MiB in all)")
                if git("add", "-f", "--", pattern, *guards.exclude_pathspecs(), check=False).returncode != 0:
                    notes.append(f"carry pattern {pattern} matched nothing")
            if agent:
                _pin_harness_config(git, head, scope)
            tree = gitio.out(git("write-tree"))
        parent = ["-p", head] if head else []
        commit = gitio.out(git("commit-tree", tree, *parent, "-m", f"carnivore job {job_id}"))
        gitio.run(["update-ref", f"refs/heads/job-{job_id}", commit], git_dir=side)
        deps: Dict[str, DepDir] = {}
        _dep_dirs(toplevel, _lockfiles(toplevel, env, git_dir, toplevel), [toplevel], deps)
        if project_root and os.path.realpath(project_root) != toplevel:
            root = os.path.realpath(project_root)
            inherited: Dict[str, DepDir] = {}
            _dep_dirs(root, _lockfiles(root, None, None, None), [toplevel, root], inherited)
            for path, dep in inherited.items():
                if path not in deps and not os.path.exists(os.path.join(toplevel, path)):
                    deps[path] = dep
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    log.info("jobs_snapshot_taken", job_id=job_id, files=len(untracked), notes=len(notes))
    return Snapshot(commit=commit, tree=tree, head=head, toplevel=toplevel, scope=scope, side_git_dir=side,
                    dep_dirs=list(deps.values()), notes=notes, outside_links=_outside_links(toplevel, scope),
                    new_bytes=max(0, _store_bytes(side) - before), taken_at=clock())

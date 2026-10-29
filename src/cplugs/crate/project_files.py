
from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from src.cplugs.crate import constants as K
from src.cplugs.crate import policy as P
from src.cplugs.crate.plan_files import PlannedFile
from src.cplugs.sdk.transcript_files import dataless

ARTIFACT = "project"
_KEY = "project/project_file"
_LINK_FILE_MODE = 0o644


@dataclass
class SkippedDir:

    rel: str
    bytes: int
    files: int
    why: str = ""


@dataclass
class ProjectWalk:

    root: str
    files: List[PlannedFile] = field(default_factory=list)
    skipped: List[SkippedDir] = field(default_factory=list)
    skipped_file_bytes: int = 0
    specials: List[str] = field(default_factory=list)
    links: int = 0
    blockers: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def file_bytes(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def skipped_bytes(self) -> int:
        return sum(d.bytes for d in self.skipped) + self.skipped_file_bytes

    def view(self) -> Dict[str, Any]:
        listed = sorted(self.skipped, key=lambda d: (-d.bytes, d.rel))[:K.PROJECT_SKIPPED_LISTED]
        return {"root": self.root, "files": len(self.files), "bytes": self.file_bytes, "links": self.links,
                "skipped": [{"path": d.rel, "bytes": d.bytes, "files": d.files} for d in listed],
                "skipped_folders": len(self.skipped), "skipped_more": len(self.skipped) - len(listed), "skipped_bytes": self.skipped_bytes,
                "specials": list(self.specials), "large": self.file_bytes > K.PROJECT_WARN_BYTES,
                "warn_bytes": K.PROJECT_WARN_BYTES}

    def excluded(self) -> List[Dict[str, Any]]:
        out = [{"kind": "policy", "store": ARTIFACT, "what": d.rel, "reason": d.why or f"skip list: {_name_of(d.rel)} ({d.bytes} bytes)"}
               for d in self.skipped]
        return out + [{"kind": "policy", "store": ARTIFACT, "what": rel,
                       "reason": "not a regular file, not readable by this user or not a UTF-8 name"}
                      for rel in self.specials]


def _name_of(rel: str) -> str:
    return rel.rsplit("/", 1)[-1]


def is_skipped(name: str) -> bool:
    return name in K.PROJECT_SKIP_NAMES or name.endswith(K.PROJECT_SKIP_SUFFIXES)


def skipped_component(rel: str) -> bool:
    return any(is_skipped(part) for part in rel.split("/"))


def tree_size(path: str) -> Tuple[int, int]:
    total, count, stack = 0, 0, [path]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total, count = total + entry.stat(follow_symlinks=False).st_size, count + 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, count


def _sample(rels: Sequence[str]) -> str:
    shown = ", ".join(rels[:K.PROJECT_SAMPLE_PATHS])
    return shown + (f" and {len(rels) - K.PROJECT_SAMPLE_PATHS} more" if len(rels) > K.PROJECT_SAMPLE_PATHS else "")


class _Walker:

    def __init__(self, root: str, deny: Set[Tuple[int, int]], plugin_roots: Dict[str, str]) -> None:
        self.root, self.deny, self.plugin_roots = root, deny, plugin_roots
        self.out = ProjectWalk(root)
        self.dataless: List[str] = []
        self.credential: List[str] = []

    def _planned(self, rel: str, full: str, role: str, st: os.stat_result, size: int, link: Optional[str]) -> PlannedFile:
        return PlannedFile(key=_KEY, role=role, home=P.HOME_PROJECT, home_index=0, rel=rel, source_path=full,
                           conversation_id=None, family=None, enc_folder=None, line_mode=False, size=size, ino=st.st_ino,
                           mtime_ns=st.st_mtime_ns, mode=st.st_mode & 0o7777, artifact=ARTIFACT, project=True,
                           link_target=link)

    def _link(self, rel: str, full: str, st: os.stat_result) -> None:
        try:
            raw = os.fsencode(os.readlink(full))
        except OSError:
            self.out.specials.append(rel)
            return
        if not raw:
            self.out.specials.append(rel)
            return
        self.out.links += 1
        planned = self._planned(rel, full, P.R_PROJECT_LINK, st, len(raw), raw.decode("utf-8", "replace"))
        planned.mode = _LINK_FILE_MODE
        self.out.files.append(planned)

    def _file(self, rel: str, full: str, st: os.stat_result) -> None:
        if (st.st_dev, st.st_ino) in self.deny:
            self.credential.append(rel)
        elif dataless.is_dataless_file(Path(full)):
            self.dataless.append(rel)
        elif not os.access(full, os.R_OK):
            self.out.specials.append(rel)
        else:
            self.out.files.append(self._planned(rel, full, P.R_PROJECT_FILE, st, st.st_size, None))

    def _entry(self, entry: "os.DirEntry[str]", rel: str, stack: List[Tuple[str, str]]) -> None:
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError:
            self.out.specials.append(rel)
            return
        try:
            rel.encode("utf-8")
        except UnicodeEncodeError:
            self.out.specials.append(rel.encode("utf-8", "replace").decode("utf-8"))
            return
        owner = self.plugin_roots.get(os.path.realpath(entry.path)) if stat.S_ISDIR(st.st_mode) else None
        if owner:
            size, count = tree_size(entry.path)
            self.out.skipped.append(SkippedDir(rel, size, count, f"the {owner} plugin store: carried by its own declaration, never as project files ({size} bytes)"))
            return
        if is_skipped(entry.name):
            if stat.S_ISDIR(st.st_mode):
                size, count = tree_size(entry.path)
                self.out.skipped.append(SkippedDir(rel, size, count))
            else:
                self.out.skipped_file_bytes += st.st_size if stat.S_ISREG(st.st_mode) else 0
            return
        if stat.S_ISLNK(st.st_mode):
            self._link(rel, entry.path, st)
        elif stat.S_ISDIR(st.st_mode):
            stack.append((entry.path, rel))
        elif stat.S_ISREG(st.st_mode):
            self._file(rel, entry.path, st)
        else:
            self.out.specials.append(rel)

    def run(self) -> ProjectWalk:
        stack: List[Tuple[str, str]] = [(self.root, "")]
        while stack:
            folder, prefix = stack.pop()
            try:
                with os.scandir(folder) as entries:
                    ordered = sorted(entries, key=lambda e: e.name)
            except OSError as exc:
                if exc.errno == errno.EDEADLK:
                    self.dataless.append(prefix or ".")
                elif prefix:
                    self.out.specials.append(prefix)
                else:
                    self.out.blockers.append((K.B_FORBIDDEN, f"the project folder itself could not be listed ({type(exc).__name__})"))
                continue
            for entry in reversed(ordered):
                self._entry(entry, f"{prefix}/{entry.name}" if prefix else entry.name, stack)
        self.out.files.sort(key=lambda f: f.rel)
        self.out.specials.sort()
        self.out.skipped.sort(key=lambda d: d.rel)
        for found, code, why in ((self.dataless, K.B_DATALESS, "files or folders only in iCloud, not on this disk"),
                                 (self.credential, K.B_FORBIDDEN, "hard links of a credential file")):
            if found:
                self.out.blockers.append((code, f"{len(found)} project {why}: {_sample(sorted(found))}"))
        return self.out


def walk_project(root: str, deny: Set[Tuple[int, int]], plugin_roots: Optional[Dict[str, str]] = None) -> ProjectWalk:
    return _Walker(os.path.realpath(root), deny, plugin_roots or {}).run()

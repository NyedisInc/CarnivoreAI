
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from src.cplugs.crate import constants as K
from src.cplugs.crate import policy as P
from src.cplugs.crate.forbidden import DatalessSource, SourceForbidden, open_source
from src.cplugs.sdk import crate_sources as cs

ORIGIN_DISK, ORIGIN_VAULT = "disk", "vault"


@dataclass
class PlannedFile:

    key: str
    role: str
    home: str
    home_index: int
    rel: str
    source_path: Optional[str]
    conversation_id: Optional[str]
    family: Optional[str]
    enc_folder: Optional[str]
    line_mode: bool
    size: int
    origin: str = ORIGIN_DISK
    copy_of: Optional[str] = None
    vault: Optional[Tuple[str, str]] = None
    ino: int = 0
    mtime_ns: int = 0
    mode: int = 0
    artifact: str = ""
    project: bool = False
    link_target: Optional[str] = None
    plugin: str = ""
    data: str = ""
    plugin_root: str = ""
    provides: str = ""
    vault_conversation: str = ""
    vault_point: str = ""
    inline: Optional[bytes] = None
    backup_unit: str = ""

    @property
    def sort_key(self) -> Tuple[str, int, str]:
        return (self.home, self.home_index, self.rel)

    def material(self) -> List[Any]:
        return [self.source_path or self.rel, self.ino, self.size, self.mtime_ns, self.origin] + (
            [self.vault[0]] if self.vault else [])


@dataclass
class FileWalk:

    files: List[PlannedFile] = field(default_factory=list)
    blockers: List[Tuple[str, str]] = field(default_factory=list)
    excluded: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    seen: Set[str] = field(default_factory=set)
    refused: Set[str] = field(default_factory=set)


def enc_of(home: str, rel: str) -> Optional[str]:
    parts = rel.split("/")
    return parts[1] if home == P.HOME_CLAUDE and parts[0] == "projects" and len(parts) >= 3 else None


class FilePlanner:

    def __init__(self, homes: P.HomesView, roots: Sequence[str], deny: Set[Tuple[int, int]], scope_ids: Sequence[str]) -> None:
        self.homes, self.roots, self.deny = homes, list(roots), deny
        self.scope_ids = list(scope_ids)
        self.walk = FileWalk()

    def _check(self, path: str) -> Optional[os.stat_result]:
        try:
            fd, st = open_source(path, self.roots, self.deny)
        except DatalessSource as exc:
            self.walk.blockers.append((K.B_DATALESS, str(exc)))
            return None
        except SourceForbidden as exc:
            self.walk.blockers.append((K.B_FORBIDDEN, str(exc)))
            return None
        except OSError as exc:
            self.walk.blockers.append((K.B_FORBIDDEN, f"{path} could not be opened ({type(exc).__name__})"))
            return None
        os.close(fd)
        return st

    def _one(self, art: cs.Artifact, decision: P.Decision, path: str, role: str, conversation: Optional[str]) -> None:
        real = os.path.realpath(path)
        if real in self.walk.seen:
            return
        self.walk.seen.add(real)
        placed = self.homes.place(path)
        if placed is None:
            self.walk.blockers.append((K.B_FORBIDDEN, f"{path} is outside every home a crate files into"))
            return
        st = self._check(path)
        if st is None:
            if role in P.MAIN_ROLES and conversation:
                self.walk.refused.add(conversation)
            return
        home, index, rel = placed
        copy = role in P.COPY_ROLES
        family = P.HOME_CODEX if home == P.HOME_CODEX else (P.HOME_CLAUDE if conversation else None)
        if role == P.R_CONFLICT:
            self.walk.warnings.append(f"{K.W_CONFLICT}: {path} is an iCloud conflict copy; it is carried, never merged")
        self.walk.files.append(PlannedFile(
            key=decision.key, role=role, home=home, home_index=index, rel=rel, source_path=path,
            conversation_id=None if copy else conversation, copy_of=conversation if copy else None, family=family,
            enc_folder=enc_of(home, rel), line_mode=P.line_mode(role, os.path.basename(path)), size=st.st_size,
            ino=st.st_ino, mtime_ns=st.st_mtime_ns, mode=st.st_mode & 0o7777, artifact=art.what))

    def add(self, art: cs.Artifact, decision: P.Decision) -> None:
        path = str(art.locator.get("path") or art.what)
        is_dir = art.kind == cs.KIND_DIR
        conversation = P.conversation_for(decision.role, path, is_dir, self.scope_ids)
        if conversation is not None and not K.CONVERSATION_ID_RE.match(conversation):
            conversation = None
        if os.path.islink(path):
            self.walk.blockers.append((K.B_FORBIDDEN, f"{path}: a symlink, never followed"))
            return
        if not is_dir:
            self._one(art, decision, path, decision.role or P.R_CONV_FILE, conversation)
            return
        for folder, dirnames, filenames in os.walk(path, followlinks=False):
            dirnames.sort()
            for name in sorted(filenames) + [d for d in dirnames if os.path.islink(os.path.join(folder, d))]:
                full = os.path.join(folder, name)
                if os.path.islink(full):
                    self.walk.excluded.append({"kind": "policy", "store": art.store, "what": full,
                                               "reason": "symlink, not followed"})
                    continue
                sub = os.path.relpath(full, path).replace(os.sep, "/")
                self._one(art, decision, full, P.file_role(decision.role, sub), conversation)


def conversation_records(sessions: Sequence[cs.SessionIdentity], scope_ids: Dict[str, Optional[cs.SessionIdentity]],
                         files: Sequence[PlannedFile]) -> Tuple[List[Dict[str, Any]], List[str]]:
    mains: Dict[str, List[PlannedFile]] = {}
    for f in files:
        if f.role in P.MAIN_ROLES and f.conversation_id:
            mains.setdefault(f.conversation_id, []).append(f)
    records: List[Dict[str, Any]] = []
    missing: List[str] = []
    for conv in sorted(scope_ids):
        ident = scope_ids[conv]
        found = mains.get(conv, [])
        codex = ident is not None and (ident.agent_family or "") == P.HOME_CODEX
        preferred = [f for f in found if (f.role == P.R_ROLLOUT) == codex]
        main = (preferred or found or [None])[0]
        if main is None:
            missing.append(conv)
            continue
        family = P.HOME_CODEX if main.role == P.R_ROLLOUT else P.HOME_CLAUDE
        records.append({"id": conv, "family": family, "title": ident.title if ident else None,
                        "session_uuid": ident.session_uuid if ident else None,
                        "working_dir": ident.working_dir if ident else None, "main_rel": main.rel,
                        "enc_folder": main.enc_folder, "origin": main.origin, "orphan": ident is None})
    return records, missing


from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

from src.cplugs.crate import constants as K
from src.cplugs.crate import policy as P
from src.cplugs.crate.forbidden import SourceForbidden, open_source
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan_files import ORIGIN_VAULT, PlannedFile
from src.cplugs.crate.source_read import SourceUnstable, disk_chunks, open_chunks, stat_unchanged, vault_chunks
from src.cplugs.crate.vault_files import VaultOpener
from src.cplugs.sdk import blob_codec as bc
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs
from src.core.deepsearch import fallback_hook as fb

Transform = Callable[[PlannedFile, Iterator[bytes]], Iterator[bytes]]
Placement = Callable[[str, str], str]


class SkipFile(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class FilesOut:

    records: List[cf.FileRecord] = field(default_factory=list)
    source_sha: Dict[str, str] = field(default_factory=dict)
    findings: Dict[str, Dict[str, int]] = field(default_factory=dict)
    harness: Dict[str, Set[str]] = field(default_factory=dict)
    plans: List[str] = field(default_factory=list)
    written: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    discovered: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)


def _open_history(path: str) -> int:
    """Open a history or index file for reading; a symlink is followed only to a regular file inside the same agent home.

    The home is the real folder holding the link (``~/.claude`` for ``history.jsonl``). A link is resolved once, its real
    path must stay below that home, and the real path is opened with ``O_NOFOLLOW`` so a swap after the check is refused.
    Output: an fd (the caller closes it). Raises: SourceForbidden (escaping link, loop, non-regular target); OSError.
    Example: ``history.jsonl -> history.jsonl.nosync`` opens ``history.jsonl.nosync``.
    """
    target = path
    if os.path.islink(path):
        home = os.path.realpath(os.path.dirname(path))
        target = os.path.realpath(path)
        if not target.startswith(home.rstrip(os.sep) + os.sep):
            raise SourceForbidden(path, "a symlink leaving the agent home, never followed")
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        if os.path.islink(target) or os.path.islink(path):
            raise SourceForbidden(path, "a symlink that cannot be followed safely") from exc
        raise
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise SourceForbidden(path, "not a regular file")
    return fd


def write_lines(sink: Any, items: Sequence[Dict[str, Any]], job: JobHandle) -> Tuple[int, Dict[str, int]]:
    groups: Dict[Tuple[str, int, str], Set[str]] = {}
    for item in items:
        groups.setdefault((item["source"], int(item["home_index"]), item["path"]), set()).add(item["match"])
    total, per_path = 0, {}
    for (source, index, path), matches in sorted(groups.items()):
        job.check()
        needles = [f'"{m}"'.encode("utf-8") for m in sorted(matches)] if source == "claude-history" else \
                  [f'"id":"{m}"'.encode("utf-8") for m in sorted(matches)]
        kept: List[bytes] = []
        fd = _open_history(path)
        with os.fdopen(fd, "rb") as handle:
            for line in handle:
                probe = line if source == "claude-history" else line.replace(b" ", b"")
                if any(n in probe for n in needles):
                    kept.append(line)
        if kept:
            sink.add_member(f"lines/{source}-{index}.jsonl", b"".join(kept))
        total += len(kept)
        per_path[path] = len(kept)
    return total, per_path


def _versions(chunk: bytes, family: Optional[str], first: bool, into: Set[str]) -> None:
    lines = chunk.split(b"\n")
    for index, line in enumerate(lines):
        if family == P.HOME_CODEX and not (first and index == 0):
            return
        if b'"version"' not in line and b'"cli_version"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        value = (record.get("payload") or {}).get("cli_version") if family == P.HOME_CODEX else record.get("version")
        value = value if isinstance(value, str) else record.get("cli_version")
        if isinstance(value, str) and 0 < len(value) <= 64:
            into.add(value)


class FileWriter:

    def __init__(self, sink: Any, plan: Any, job: JobHandle, *, transform: Optional[Transform] = None,
                 place: Optional[Placement] = None, scan: bool = True, plan_homes: Sequence[str] = ()) -> None:
        self.sink, self.plan, self.job = sink, plan, job
        self.transform, self.place, self.scan, self.plan_homes = transform, place, scan, list(plan_homes)
        self.out = FilesOut()
        self._deny: Set[Tuple[int, int]] = set()
        self._opener: Optional[VaultOpener] = None

    def _record(self, pf: PlannedFile, refs: List[Any], digest: Any, length: int, lines: int, last: bytes,
                st: Optional[os.stat_result]) -> cf.FileRecord:
        rel, source, enc = pf.rel, pf.source_path, pf.enc_folder
        if self.place is not None:
            rel, source, enc = self.place(pf.home, pf.rel), None, None
        return cf.FileRecord(
            role=pf.role, home=pf.home, home_index=pf.home_index, rel=rel, source_path=source,
            conversation_id=pf.conversation_id, family=pf.family, enc_folder=enc, length=length,
            content_sha256=digest.hexdigest(), chain_sha256=bc.chain_sha(refs), chunks=tuple(refs), line_mode=pf.line_mode,
            lines=lines if pf.line_mode else None, ends_with_newline=last.endswith(b"\n") or length == 0,
            mode=(st.st_mode & 0o777) if st is not None else pf.mode, mtime_ns=st.st_mtime_ns if st else (pf.mtime_ns or None),
            origin=pf.origin, vault_signature=pf.vault[0] if pf.vault else None, redactions=None,
            extra=({"copy_of": pf.copy_of} if pf.copy_of else {}) | ({"plugin": pf.plugin, "data": pf.data} if pf.plugin else {})
                   | ({"provides": pf.provides} if pf.provides else {}) | ({"backup_unit": pf.backup_unit} if pf.backup_unit else {}))

    def _consume(self, pf: PlannedFile, chunks: Iterable[bytes]) -> Tuple[List[Any], Any, int, int, bytes]:
        refs, digest, length, lines, last = [], hashlib.sha256(), 0, 0, b""
        conversation = pf.conversation_id
        versions = self.out.harness.setdefault(conversation, set()) if conversation and pf.line_mode else None
        where = f"{pf.home}/{pf.home_index}/{pf.rel}"
        for index, chunk in enumerate(chunks):
            started = time.monotonic()
            self.job.check()
            refs.append(self.sink.add_blob(chunk))
            digest.update(chunk)
            length += len(chunk)
            lines += chunk.count(b"\n") if pf.line_mode else 0
            last = chunk
            if versions is not None and pf.role in (P.R_TRANSCRIPT, P.R_SUBAGENT, P.R_ROLLOUT, P.R_ORPHAN):
                _versions(chunk, pf.family, index == 0, versions)
            if self.plan_homes and pf.role in (P.R_TRANSCRIPT, P.R_SUBAGENT):
                for slug in cs.plan_slugs(chunk, self.plan_homes):
                    if slug not in self.out.plans:
                        self.out.plans.append(slug)
            if self.scan:
                for detector, n in cs.scan_counts(chunk.decode("utf-8", "replace")).items():
                    found = self.out.findings.setdefault(where, {})
                    found[detector] = found.get(detector, 0) + n
            self.job.add(len(chunk))
            self.job.rest(time.monotonic() - started)
        return refs, digest, length, lines, last

    def _transformed(self, pf: PlannedFile, raw: Iterator[bytes]) -> Optional[Tuple[List[Any], Any, int, int, bytes]]:
        chunks = self.transform(pf, raw) if self.transform is not None else raw
        try:
            return self._consume(pf, chunks)
        except SkipFile as exc:
            self.out.skipped.append({"kind": "policy", "store": pf.key.rsplit("/", 1)[0], "reason": exc.reason})
            return None

    def write_disk(self, pf: PlannedFile) -> Optional[cf.FileRecord]:
        roots = [pf.plugin_root] if pf.plugin_root else ([str(self.plan.project_root)] if pf.project else self.plan.roots)
        fd, before = open_source(str(pf.source_path), roots, self._deny, names=not pf.project)
        try:
            raw = disk_chunks(fd, before, pf.line_mode, str(pf.source_path))
            source_digest = hashlib.sha256()

            def tapped() -> Iterator[bytes]:
                for chunk in raw:
                    source_digest.update(chunk)
                    yield chunk

            done = self._transformed(pf, tapped())
            if done is None:
                return None
            refs, digest, length, lines, last = done
            after = os.fstat(fd)
        finally:
            os.close(fd)
        if not stat_unchanged(before, after) or not stat_unchanged(before, os.stat(str(pf.source_path))):
            raise SourceUnstable(str(pf.source_path))
        self.out.source_sha[str(pf.source_path)] = source_digest.hexdigest()
        return self._record(pf, refs, digest, length, lines, last, before)

    def write_vault(self, pf: PlannedFile) -> Optional[cf.FileRecord]:
        if self._opener is None:
            self._opener = VaultOpener()
        reader = self._opener.open(pf)
        where = f"{pf.conversation_id}/{pf.rel}"

        def guarded() -> Iterator[bytes]:
            try:
                yield from vault_chunks(reader, pf.line_mode, pace=self.job.check)
            except (fb.FallbackUnavailable, OSError, SourceUnstable) as exc:
                raise cs.SourceUnavailable(f"{where} could not be read from the backup ({type(exc).__name__})") from exc

        done = self._transformed(pf, guarded())
        return None if done is None else self._record(pf, *done, None)

    def write_link(self, pf: PlannedFile) -> cf.FileRecord:
        raw = os.fsencode(os.readlink(str(pf.source_path)))
        if raw.decode("utf-8", "replace") != pf.link_target:
            raise SourceUnstable(str(pf.source_path))
        done = self._consume(pf, iter([raw]))
        record = self._record(pf, *done, None)
        return replace(record, extra={**record.extra, "link_target": pf.link_target})

    def write_inline(self, pf: PlannedFile) -> cf.FileRecord:
        done = self._consume(pf, open_chunks(iter([pf.inline or b""]), False))
        return self._record(pf, *done, None)

    def write(self, pf: PlannedFile) -> Optional[cf.FileRecord]:
        if pf.inline is not None:
            return self.write_inline(pf)
        if pf.link_target is not None:
            return self.write_link(pf)
        return self.write_vault(pf) if pf.origin == ORIGIN_VAULT else self.write_disk(pf)

    def add(self, record: cf.FileRecord, pf: PlannedFile) -> None:
        self.out.records.append(record)
        count, size = self.out.written.get(pf.artifact, (0, 0))
        self.out.written[pf.artifact] = (count + 1, size + record.length)
        self.job.add(0, files=1)

    def discovered_plans(self, homes: Sequence[str]) -> List[PlannedFile]:
        found: List[PlannedFile] = []
        for slug in sorted(self.out.plans):
            hits = [(i, Path(h) / "plans" / f"{slug}.md") for i, h in enumerate(homes)]
            hits = [(i, p) for i, p in hits if p.is_file() and not p.is_symlink()]
            if not hits:
                self.out.warnings.append(f"{K.W_PLAN_ABSENT}: a carried transcript names plans/{slug}.md, which is not on disk")
                continue
            for index, path in hits:
                st = os.stat(path)
                found.append(PlannedFile(key="claude/plan", role=P.R_PLAN, home=P.HOME_CLAUDE, home_index=index,
                                         rel=f"plans/{slug}.md", source_path=str(path), conversation_id=None, family=None,
                                         enc_folder=None, line_mode=False, size=st.st_size, ino=st.st_ino,
                                         mtime_ns=st.st_mtime_ns, artifact=str(path)))
                self.out.discovered.append({"store": "claude", "kind": "file", "what": str(path), "inventory_count": 0,
                                            "inventory_size": 0, "decision": P.CARRY,
                                            "reason": "a plan file a carried transcript names", "status": "discovered"})
        return found

    def set_deny(self, deny: Set[Tuple[int, int]]) -> None:
        self._deny = set(deny)

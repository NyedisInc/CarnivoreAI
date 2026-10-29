"""The far box's Codex stores, read over ssh (issue #162, follow-up #1049).

A local codex session is lit from four surfaces (``attention/codex_reader.py``):
its own turn record in ``~/.codex/thread_history_*.sqlite``, the rollout tail
under ``~/.codex/sessions``, the writer lock under
``~/.codex/thread-writer-locks``, and the pane. This reads the first three ON
THE HOST THE SESSION RUNS ON and hands them to the SAME pure mapping the local
reader uses (``codex_stores.codex_record_facts`` and
``codex_transcript_facts``), so a remote codex row gets the same tiers.

ONE EXEC PER HOST PER WATCHER PASS prints, framed by a per-exec random marker:

THE PICK IS THE LOCAL PANE-OWNED RULE: the one non-archived ``user`` thread
whose writer lock a descendant of the far pane holds. One codex process holds
its sub-agents' locks too, so the ``threads`` source is what tells them apart.

READ ONLY, AND ONLY THESE FILES: the state db, the history db, ``sessions/``
and the lock directory (:data:`CODEX_READ_SCOPE`). Nothing here names
``auth.json`` or any other file under ``~/.codex``; a rollout is read only
when it is a regular file, not a symlink, under ``~/.codex/sessions`` that
names its own thread.

DEGRADING HONESTLY. No ``sqlite3``, an unreadable db or a schema that does not
answer the queries leaves the record tier absent; no ``lsof`` or no process
table leaves no pick. Absent tiers resolve ``unknown`` and the pane tier still
answers. A host that could not be asked reads nothing for that pass.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

import structlog

from src.core.attention.codex_reader import CodexEvidence, CodexRecordFacts, CodexTranscriptFacts
from src.core.attention.codex_stores import (
    ROLLOUT_TAIL_BYTES, codex_record_facts, codex_transcript_facts)
from src.core.hosts.remote_claude_files import (
    DELTA_MAX_BYTES, UUID_RE, exec_sync, fetch_window, split_frames)
from src.core.hosts.remote_host import RemoteHostUnavailable

logger = structlog.get_logger()

CODEX_READ_SCOPE = ("state_*.sqlite", "thread_history_*.sqlite", "sessions/",
                    "thread-writer-locks/")

MAX_THREADS = 64

PS_MAX_BYTES = 192 * 1024
LSOF_MAX_BYTES = 128 * 1024
SQL_MAX_BYTES = 64 * 1024


def pass_script(marker: str, held: Mapping[str, int]) -> str:
    specs = " ".join(f"{u}:{int(k)}" for u, k in held.items() if UUID_RE.fullmatch(u))
    sqlite = "sqlite3 -readonly -batch -bail -noheader -list -cmd '.timeout 500'"
    return (
        f"LC_ALL=C; export LC_ALL; M='{marker}'; C=\"$HOME/.codex\"; printf '\\n'\n"
        "if p=$(ps -A -o pid=,ppid= 2>/dev/null); then\n"
        f"  printf '%s P\\n' \"$M\"; printf '%s\\n' \"$p\" | head -c {PS_MAX_BYTES}; printf '\\n'\n"
        "fi\n"
        "ids=\n"
        "if command -v lsof >/dev/null 2>&1; then\n"
        f"  l=$(lsof -F pn -- \"$C\"/thread-writer-locks/*.lock 2>/dev/null | head -c {LSOF_MAX_BYTES})\n"
        "  printf '%s L\\n%s\\n' \"$M\" \"$l\"\n"
        "  ids=$(printf '%s\\n' \"$l\" | sed -n "
        "'s#^n.*/thread-writer-locks/\\([0-9a-fA-F-]\\{36\\}\\)\\.lock$#\\1#p' "
        f"| sort -u | head -n {MAX_THREADS})\n"
        "fi\n"
        "if [ -n \"$ids\" ]; then\n"
        "  q=; for u in $ids; do q=\"$q${q:+,}'$u'\"; done\n"
        "  if command -v sqlite3 >/dev/null 2>&1; then\n"
        "    rd() {\n"
        "      if [ -z \"$2\" ]; then printf '%s %s -\\n' \"$M\" \"$1\"; return; fi\n"
        f"      if [ -e \"$2-wal\" ]; then o=$({sqlite} \"$2\" \"$3\" 2>/dev/null)\n"
        f"      else o=$({sqlite} \"file:$2?immutable=1\" \"$3\" 2>/dev/null); fi\n"
        "      r=$?; printf '%s %s %s\\n' \"$M\" \"$1\" \"$r\"\n"
        f"      printf '%s\\n' \"$o\" | head -c {SQL_MAX_BYTES}\n"
        "    }\n"
        "    s=; for f in \"$C\"/state_*.sqlite; do [ -f \"$f\" ] && s=$f; done\n"
        "    h=; for f in \"$C\"/thread_history_*.sqlite; do [ -f \"$f\" ] && h=$f; done\n"
        "    rd U \"$s\" \"SELECT id, thread_source, archived FROM threads WHERE id IN ($q);\"\n"
        "    rd T \"$h\" \"SELECT t.thread_id, t.status FROM thread_turns t WHERE t.thread_id "
        "IN ($q) AND t.rollout_ordinal = (SELECT MAX(rollout_ordinal) FROM thread_turns "
        "WHERE thread_id = t.thread_id);\"\n"
        "    rd O \"$h\" \"SELECT thread_id, next_rollout_byte_offset FROM "
        "thread_history_projection_state WHERE thread_id IN ($q);\"\n"
        "  else printf '%s Q\\n' \"$M\"; fi\n"
        "  for u in $ids; do\n"
        f"    k=-1; for spec in {specs}; do [ \"${{spec%%:*}}\" = \"$u\" ] && k=${{spec#*:}}; done\n"
        "    best=; for f in \"$C\"/sessions/*/*/*/rollout-*-\"$u\".jsonl; do "
        "[ -f \"$f\" ] && [ ! -L \"$f\" ] && best=$f; done\n"
        "    if [ -z \"$best\" ]; then printf '%s R %s -\\n' \"$M\" \"$u\"; continue; fi\n"
        "    bs=$(wc -c < \"$best\" | tr -d ' ')\n"
        f"    if [ \"$k\" -ge 0 ] && [ \"$bs\" -gt \"$k\" ] && [ $((bs-k)) -le {DELTA_MAX_BYTES} ]; then\n"
        "      printf '%s R %s %s D %s\\n' \"$M\" \"$u\" \"$bs\" \"$best\"\n"
        "      tail -c +$((k+1)) \"$best\" | head -c $((bs-k)); printf '\\n'\n"
        "    else printf '%s R %s %s S %s\\n' \"$M\" \"$u\" \"$bs\" \"$best\"; fi\n"
        "  done\n"
        "fi\n"
        "printf '%s E\\n' \"$M\"\n")


def parse_lsof(data: bytes) -> Dict[str, Set[int]]:
    holders: Dict[str, Set[int]] = {}
    pid: Optional[int] = None
    for raw in data.decode("utf-8", "replace").splitlines():
        if raw.startswith("p") and raw[1:].isdigit():
            pid = int(raw[1:])
        elif raw.startswith("n") and pid is not None and raw.endswith(".lock") \
                and "/thread-writer-locks/" in raw:
            uuid = raw.rsplit("/", 1)[-1][:-len(".lock")]
            if UUID_RE.fullmatch(uuid):
                holders.setdefault(uuid, set()).add(pid)
    return holders


def parse_parents(data: bytes) -> Dict[int, int]:
    parents: Dict[int, int] = {}
    for raw in data.split(b"\n"):
        words = raw.split()
        if len(words) == 2 and words[0].isdigit() and words[1].isdigit():
            parents[int(words[0])] = int(words[1])
    return parents


def descendants_of(root: int, parents: Mapping[int, int]) -> Set[int]:
    children: Dict[int, List[int]] = {}
    for pid, ppid in parents.items():
        children.setdefault(ppid, []).append(pid)
    found, todo = {root}, [root]
    while todo:
        for child in children.get(todo.pop(), ()):
            if child not in found:
                found.add(child)
                todo.append(child)
    return found


def _sql_rows(data: bytes, width: int) -> List[List[str]]:
    rows = []
    for raw in data.decode("utf-8", "replace").splitlines():
        fields = raw.split("|")
        if len(fields) == width and UUID_RE.fullmatch(fields[0]):
            rows.append(fields)
    return rows


def rollout_path_ok(path: str, uuid: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return ("/.codex/sessions/" in path and "/../" not in path and name.startswith("rollout-")
            and name.endswith(f"-{uuid}.jsonl"))


@dataclass
class _Rollout:

    path: str
    start: int
    end: int
    data: bytes


class FarCodexFiles:

    def __init__(self, host_key: str) -> None:
        self.host_key = host_key
        self._lock = threading.Lock()
        self.parents: Optional[Dict[int, int]] = None
        self.holders: Optional[Dict[str, Set[int]]] = None
        self.threads: Optional[Dict[str, Tuple[str, bool]]] = None
        self.statuses: Optional[Dict[str, str]] = None
        self.offsets: Dict[str, int] = {}
        self.detail = ""
        self._sizes: Dict[str, Optional[int]] = {}
        self._paths: Dict[str, str] = {}
        self._windows: Dict[str, _Rollout] = {}

    def refresh(self, host: Any) -> bool:
        """Read the far locks, the stores of every lock-held thread and their rollouts. THREAD BODY.

        Output: bool - False when the host could not be asked or answered a
          cut-short frame set (nothing is updated then).
        """
        marker = "@@x" + secrets.token_hex(8)
        with self._lock:
            held = {u: w.end for u, w in self._windows.items()}
        try:
            result = exec_sync(host, pass_script(marker, held))
        except RemoteHostUnavailable as exc:
            logger.info("remote_codex_files_unavailable", host=self.host_key, error=str(exc))
            return False
        frames = split_frames(result.stdout, marker) if result.returncode == 0 else None
        if frames is None:
            logger.info("remote_codex_files_incomplete", host=self.host_key,
                        returncode=result.returncode)
            return False
        self._apply(frames, held)
        return True

    def _apply(self, frames: List[Tuple[str, bytes]], held: Mapping[str, int]) -> None:
        parents = holders = threads = statuses = None
        offsets: Dict[str, int] = {}
        sizes: Dict[str, Optional[int]] = {}
        detail = ""
        for header, data in frames:
            kind, _, rest = header.partition(" ")
            ok = rest.strip() == "0"
            if kind == "P":
                parents = parse_parents(data)
            elif kind == "L":
                holders = parse_lsof(data)
            elif kind == "Q":
                detail = f"host {self.host_key} has no sqlite3, so codex's turn record was not read"
            elif kind in ("U", "T", "O") and not ok:
                detail = (f"a codex store on host {self.host_key} is missing, unreadable or of "
                          f"an unknown schema ({kind} answered {rest.strip() or '-'})")
            elif kind == "U":
                threads = {r[0]: (r[1], r[2].strip() not in ("", "0")) for r in _sql_rows(data, 3)}
            elif kind == "T":
                statuses = {r[0]: r[1] for r in _sql_rows(data, 2)}
            elif kind == "O":
                offsets = {r[0]: int(r[1]) for r in _sql_rows(data, 2) if r[1].isdigit()}
            elif kind == "R":
                self._apply_rollout(rest, data, held, sizes)
        with self._lock:
            self.parents, self.holders, self.threads = parents, holders, threads
            self.statuses, self.offsets, self.detail = statuses, offsets, detail
            self._sizes = sizes
            for uuid in [u for u in self._paths if u not in sizes]:
                self._paths.pop(uuid, None)
                self._windows.pop(uuid, None)

    def _apply_rollout(self, rest: str, data: bytes, held: Mapping[str, int],
                       sizes: Dict[str, Optional[int]]) -> None:
        words = rest.split(" ", 3)
        uuid = words[0]
        if not UUID_RE.fullmatch(uuid):
            return
        if len(words) < 4 or not words[1].isdigit() or not rollout_path_ok(words[3], uuid):
            sizes[uuid] = None
            return
        size, mode, path = int(words[1]), words[2], words[3]
        sizes[uuid] = size
        self._paths[uuid] = path
        if mode != "D":
            return
        with self._lock:
            window = self._windows.get(uuid)
            if window is None or window.end != held.get(uuid) or window.path != path:
                return
            window.data += data
            window.end += len(data)
            cut = len(window.data) - ROLLOUT_TAIL_BYTES
            if cut > 0:
                window.data, window.start = window.data[cut:], window.start + cut

    def pick(self, far_pane_pid: Optional[int]) -> Optional[str]:
        with self._lock:
            parents, holders, threads = self.parents, self.holders, self.threads
        if far_pane_pid is None or parents is None or holders is None or threads is None:
            return None
        below = descendants_of(int(far_pane_pid), parents)
        owned = {u for u, pids in holders.items() if pids & below
                 and threads.get(u, ("", True))[0] == "user" and not threads[u][1]}
        return next(iter(owned)) if len(owned) == 1 else None

    def evidence(self, host: Any, uuid: str, now: datetime) -> CodexEvidence:
        with self._lock:
            statuses, offsets, detail = self.statuses, dict(self.offsets), self.detail
            size = self._sizes.get(uuid)
        record = (CodexRecordFacts() if statuses is None else codex_record_facts(
            statuses.get(uuid), offsets.get(uuid), lock_live=True, rollout_size=size))
        return CodexEvidence(record=record, transcript=self._transcript(host, uuid, now),
                             detail=detail or f"codex evidence gathered from host {self.host_key}")

    def _transcript(self, host: Any, uuid: str, now: datetime) -> CodexTranscriptFacts:
        with self._lock:
            size, path = self._sizes.get(uuid), self._paths.get(uuid)
            window = self._windows.get(uuid)
        if size is None or path is None:
            return CodexTranscriptFacts(readable=False, detail="no codex rollout on the far box")
        if window is None or window.end != size or window.path != path:
            fetched = fetch_window(host, path, ROLLOUT_TAIL_BYTES)
            if fetched is None:
                return CodexTranscriptFacts(readable=False,
                                            detail="the far codex rollout could not be read")
            window = _Rollout(fetched.path, fetched.start, fetched.end, fetched.data)
            with self._lock:
                self._windows[uuid] = window
        lines = window.data.decode("utf-8", errors="replace").split("\n")
        if window.start > 0 and lines:
            lines = lines[1:]
        return codex_transcript_facts([ln for ln in lines if ln.strip()], now=now)


def files_for(host: Any) -> FarCodexFiles:
    files = getattr(host, "codex_files", None)
    if not isinstance(files, FarCodexFiles):
        files = FarCodexFiles(host.host_key)
        host.codex_files = files
    return files


def codex_evidence_for(manager: Any, remote_pass: Any, backend: Any, pane_row: Mapping[str, Any],
                       epoch: Optional[int], now: datetime
                       ) -> Tuple[CodexEvidence, Optional[str], Optional[str]]:
    files, rows = remote_pass.codex_files(manager, backend.host, now)
    row_uuid = rows.get((str(backend.tmux_session), epoch)) if epoch is not None else None
    if files is None:
        return CodexEvidence(detail=f"host {backend.host_key}'s codex stores were not read "
                                    "this pass"), None, row_uuid
    picked = files.pick(pane_row.get("far_pid"))
    if picked is None:
        return CodexEvidence(detail=files.detail or "no codex conversation is measured as "
                                    "owned by this far pane"), None, row_uuid
    return (files.evidence(backend.host, picked, now),
            picked if picked != row_uuid else None, picked)


def bind_codex_conversation(manager: Any, session_id: str, evidence: Any) -> Optional[str]:
    from src.core.hosts.identity import is_remote_backend
    from src.core.hosts.remote_resume import _bind_write

    backend = manager._registry.backends.get(session_id)
    uuid = getattr(evidence, "codex_bind_uuid", None)
    identity = getattr(evidence, "identity", None) or ()
    epoch = identity[2] if len(identity) > 2 else None
    if not is_remote_backend(backend) or not uuid or not UUID_RE.fullmatch(uuid) or epoch is None:
        return None
    changed = (_bind_write(manager, backend, epoch, uuid, False)
               or _bind_write(manager, backend, epoch, uuid, True))
    if not changed:
        return None
    logger.info("remote_codex_conversation_bound", host=backend.host_key, session_id=session_id)
    return uuid

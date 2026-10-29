
from __future__ import annotations

import asyncio
import json
import re
import secrets
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

import structlog

from src.core.attention.registry_read import (
    MAX_REGISTRY_FILE_BYTES, RegistryRecord, index_registry_records, load_registry_blob)
from src.core.attention.transcript_contract import against_contract
from src.core.attention.transcript_facts import (
    FACTS_SHAPE_UNRECOGNIZED, FACTS_TAIL_BYTES, FACTS_UNREADABLE, TranscriptFacts,
    classify_transcript_records)
from src.core.hosts.remote_host import RemoteHostUnavailable
from src.core.hosts.ssh_exec import posix_quote

logger = structlog.get_logger()

# conversation id
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

REGISTRY_SCAN_LIMIT = 128

DELTA_MAX_BYTES = 64 * 1024

TAIL_BYTES = FACTS_TAIL_BYTES

WIDE_TAIL_BYTES = 768 * 1024

EXEC_TIMEOUT_SECONDS = 8.0


def exec_sync(host: Any, script: str, timeout: float = EXEC_TIMEOUT_SECONDS) -> Any:
    loop = getattr(host, "loop", None)
    if loop is None:
        raise RemoteHostUnavailable(f"host {host.host_key} is not prepared")
    future = asyncio.run_coroutine_threadsafe(host.exec(script=script, timeout=timeout), loop)
    try:
        return future.result(timeout + 2.0)
    except FutureTimeout as exc:
        future.cancel()
        raise RemoteHostUnavailable(f"host {host.host_key}: a file read timed out",
                                    timed_out=True) from exc


def pass_script(marker: str, wanted: Mapping[str, int]) -> str:
    specs = " ".join(f"{uuid}:{int(end)}" for uuid, end in wanted.items() if UUID_RE.fullmatch(uuid))
    return (
        f"LC_ALL=C; export LC_ALL; M='{marker}'; printf '\\n'; n=0\n"
        'for f in "$HOME"/.claude/sessions/*.json; do\n'
        '  [ -f "$f" ] || continue; b=${f##*/}\n'
        "  case $b in *[!A-Za-z0-9._-]*) continue;; esac\n"
        f"  n=$((n+1)); [ $n -gt {REGISTRY_SCAN_LIMIT} ] && break\n"
        f"  printf '%s R %s\\n' \"$M\" \"$b\"; head -c {MAX_REGISTRY_FILE_BYTES} \"$f\"; printf '\\n'\n"
        "done\n"
        "if p=$(ps -A -o pid= 2>/dev/null); then printf '%s P\\n%s\\n' \"$M\" \"$p\"; fi\n"
        f"for spec in {specs}; do\n"
        '  u=${spec%%:*}; k=${spec#*:}; best=; bs=-1\n'
        '  for f in "$HOME"/.claude/projects/*/"$u".jsonl; do\n'
        '    [ -f "$f" ] || continue; s=$(wc -c < "$f" | tr -d " ")\n'
        '    if [ "$s" -gt "$bs" ]; then bs=$s; best=$f; fi\n'
        "  done\n"
        "  if [ -z \"$best\" ]; then printf '%s T %s -\\n' \"$M\" \"$u\"; continue; fi\n"
        f'  if [ "$k" -ge 0 ] && [ "$bs" -gt "$k" ] && [ $((bs-k)) -le {DELTA_MAX_BYTES} ]; then\n'
        "    printf '%s T %s %s D %s\\n' \"$M\" \"$u\" \"$bs\" \"$best\"\n"
        "    tail -c +$((k+1)) \"$best\" | head -c $((bs-k)); printf '\\n'\n"
        "  else printf '%s T %s %s S %s\\n' \"$M\" \"$u\" \"$bs\" \"$best\"; fi\n"
        "done\n"
        "printf '%s E\\n' \"$M\"\n")


def split_frames(stdout: bytes, marker: str) -> Optional[List[Tuple[str, bytes]]]:
    frames: List[Tuple[str, bytes]] = []
    for part in stdout.split(b"\n" + marker.encode("ascii") + b" ")[1:]:
        header, _, data = part.partition(b"\n")
        frames.append((header.decode("utf-8", "replace"), data))
    if not frames or frames[-1][0] != "E":
        return None
    return frames


@dataclass
class _Window:

    path: str
    start: int
    end: int
    data: bytes
    facts: Optional[TranscriptFacts] = None
    facts_end: int = -1


def _records(data: bytes, partial_head: bool) -> List[dict]:
    lines = data.split(b"\n")
    if partial_head and lines:
        lines = lines[1:]
    out: List[dict] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(record, dict):
            out.append(record)
    return out


def classify_window(data: bytes, start: int, now: Optional[datetime]) -> TranscriptFacts:
    records = _records(data, start > 0)
    facts = classify_transcript_records(records, now=now, window_is_whole_file=start == 0)
    return against_contract(facts, records, FACTS_SHAPE_UNRECOGNIZED)


def _unreadable(detail: str) -> TranscriptFacts:
    return TranscriptFacts(verdict=FACTS_UNREADABLE, detail=detail)


class FarClaudeFiles:

    def __init__(self, host_key: str) -> None:
        self.host_key = host_key
        self._lock = threading.Lock()
        self.registry: Dict[str, RegistryRecord] = {}
        self._sizes: Dict[str, Optional[int]] = {}
        self._paths: Dict[str, str] = {}
        self._windows: Dict[str, _Window] = {}
        self._seen_uuids: Set[str] = set()
        self.bound: Dict[Tuple[str, int], str] = {}

    def wanted(self, row_uuids: Iterable[Optional[str]]) -> Dict[str, int]:
        uuids = {u for u in row_uuids if u and UUID_RE.fullmatch(u)} | self._seen_uuids
        with self._lock:
            return {u: (self._windows[u].end if u in self._windows else -1) for u in sorted(uuids)}

    def refresh(self, host: Any, row_uuids: Iterable[Optional[str]]) -> bool:
        """Read the registry, the far pids and every wanted transcript's size. THREAD BODY.

        Output: bool - False when the host could not be asked or answered a
          cut-short frame set (nothing is updated then).
        """
        marker = "@@c" + secrets.token_hex(8)
        wanted = self.wanted(row_uuids)
        try:
            result = exec_sync(host, pass_script(marker, wanted))
        except RemoteHostUnavailable as exc:
            logger.info("remote_claude_files_unavailable", host=self.host_key, error=str(exc))
            return False
        frames = split_frames(result.stdout, marker) if result.returncode == 0 else None
        if frames is None:
            logger.info("remote_claude_files_incomplete", host=self.host_key,
                        returncode=result.returncode)
            return False
        self._apply(frames, wanted)
        return True

    def _apply(self, frames: List[Tuple[str, bytes]], wanted: Mapping[str, int]) -> None:
        loaded: List[Tuple[str, RegistryRecord]] = []
        pids: Optional[Set[int]] = None
        sizes: Dict[str, Optional[int]] = {}
        for header, data in frames:
            kind, _, rest = header.partition(" ")
            if kind == "R":
                loaded.append((rest, load_registry_blob(rest, data)))
            elif kind == "P":
                pids = {int(w) for w in data.split() if w.isdigit()}
            elif kind == "T":
                self._apply_transcript(rest, data, wanted, sizes)
        running = (lambda pid: None if pid is None or pid <= 0 or pids is None else pid in pids)
        index = index_registry_records(loaded, running)
        with self._lock:
            self.registry = index
            self._sizes = sizes
            self._seen_uuids = {r.session_uuid for r in index.values()
                                if r.session_uuid and UUID_RE.fullmatch(r.session_uuid)}

    def _apply_transcript(self, rest: str, data: bytes, wanted: Mapping[str, int],
                          sizes: Dict[str, Optional[int]]) -> None:
        words = rest.split(" ", 3)
        uuid = words[0]
        if uuid not in wanted:
            return
        if len(words) < 4 or not words[1].isdigit():
            sizes[uuid] = None
            with self._lock:
                self._windows.pop(uuid, None)
            return
        size, mode, path = int(words[1]), words[2], words[3]
        sizes[uuid] = size
        self._paths[uuid] = path
        if mode != "D":
            return
        with self._lock:
            window = self._windows.get(uuid)
            if window is None or window.end != wanted[uuid] or window.path != path:
                return
            window.data += data
            window.end += len(data)
            cut = len(window.data) - TAIL_BYTES
            if cut > 0:
                window.data, window.start = window.data[cut:], window.start + cut

    def transcript_present(self, uuid: Optional[str]) -> Optional[bool]:
        with self._lock:
            if not uuid or uuid not in self._sizes:
                return None
            return self._sizes[uuid] is not None

    def transcript_facts(self, host: Any, uuid: Optional[str],
                         now: Optional[datetime] = None) -> TranscriptFacts:
        if not uuid:
            return _unreadable("no claude conversation is bound to this row")
        with self._lock:
            size = self._sizes.get(uuid, -1)
            path = self._paths.get(uuid)
            window = self._windows.get(uuid)
        if size == -1:
            return _unreadable("the far transcript was not measured this pass")
        if size is None or path is None:
            return _unreadable(f"no transcript for {uuid} on host {self.host_key}")
        if window is None or window.end != size or window.path != path:
            window = self._fetch(host, path, TAIL_BYTES)
            if window is None:
                return _unreadable(f"the transcript on host {self.host_key} could not be read")
            with self._lock:
                self._windows[uuid] = window
        if window.facts is not None and window.facts_end == window.end:
            return window.facts
        facts = classify_window(window.data, window.start, now)
        single_line = b"\n" not in window.data.rstrip(b"\n")
        if window.start > 0 and (facts.turn_end_outside_window or single_line):
            wide = self._fetch(host, path, WIDE_TAIL_BYTES)
            if wide is not None:
                facts = classify_window(wide.data, wide.start, now)
        window.facts, window.facts_end = facts, window.end
        return facts

    def _fetch(self, host: Any, path: str, nbytes: int) -> Optional[_Window]:
        return fetch_window(host, path, nbytes)


def fetch_window(host: Any, path: str, nbytes: int) -> Optional[_Window]:
    quoted = posix_quote(path)
    script = (f"LC_ALL=C; export LC_ALL; f={quoted}; s=$(wc -c < \"$f\" | tr -d ' ') || exit 3; "
              f"a=$((s > {int(nbytes)} ? s - {int(nbytes)} : 0)); printf '%s %s\\n' \"$s\" \"$a\"; "
              "tail -c +$((a+1)) \"$f\" | head -c $((s-a))")
    try:
        result = exec_sync(host, script)
    except RemoteHostUnavailable as exc:
        logger.info("remote_transcript_fetch_failed", host=host.host_key, error=str(exc))
        return None
    head, _, data = result.stdout.partition(b"\n")
    words = head.split()
    if result.returncode != 0 or len(words) != 2 or not all(w.isdigit() for w in words):
        return None
    start = int(words[1])
    return _Window(path=path, start=start, end=start + len(data), data=data)


def files_for(host: Any) -> FarClaudeFiles:
    files = getattr(host, "claude_files", None)
    if not isinstance(files, FarClaudeFiles):
        files = FarClaudeFiles(host.host_key)
        host.claude_files = files
    return files


async def far_transcript_presence(host: Any, uuid: str) -> Tuple[str, str]:
    if not UUID_RE.fullmatch(uuid or ""):
        return "unchecked", "the conversation id is not a uuid"
    script = ('for f in "$HOME"/.claude/projects/*/' + uuid + '.jsonl; do '
              '[ -f "$f" ] && { echo present; exit 0; }; done; echo absent')
    try:
        result = await host.exec(script=script, timeout=EXEC_TIMEOUT_SECONDS)
    except RemoteHostUnavailable as exc:
        return "unchecked", str(exc)
    answer = result.stdout_text.strip()
    if result.returncode == 0 and answer == "absent":
        return "absent", (f"the conversation this session would resume ({uuid}) has no "
                          f"transcript on host {host.host_key}, so restarting it would open "
                          "a pane that exits at once")
    return ("present", "") if answer == "present" else ("unchecked", "")

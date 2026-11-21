#!/usr/bin/env python3
"""Read-only census of a Claude Code transcript corpus, the T0 spike of the session timeline plan.

Its one job: stream every transcript under a corpus root and print the numbers the timeline design rests on
(record and attachment type counts, queue-operation behavior, the pasted-content wrapper threshold, file ages,
line sizes, projected index bytes) as one JSON document. It never writes into the corpus and never prints
transcript text, only counts, lengths and shapes. Tag and tool names are bucketed (a fixed allow-list, MCP tools
collapsed to "mcp:*") so no private server or tag name reaches the report.

Exit codes: 0 census printed, 2 could not run (corpus absent or empty; never a pass).

Usage:
    python3 scripts/timeline/census.py [--corpus DIR] [--max-seconds N] [--limit-files N] [--out FILE]
Default corpus: realpath of ~/.claude/projects (a link into Application Support).
"""

from __future__ import annotations

import argparse
import bisect
import collections
import hashlib
import itertools
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Counter, Dict, Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cleanup_probe import cleanup_evidence  # noqa: E402
from index_probe import IndexCounts, probe_row_bytes, project_index  # noqa: E402

EXIT_OK = 0
EXIT_COULD_NOT_RUN = 2
MAX_PARSE_BYTES = 1 << 20
OVERSIZE_PREFIX = 4096
LENGTH_EDGES = (0, 200, 500, 800, 1000, 1500, 2000, 5000, 10000, 50000, 10**12)
PAIR_WINDOW = 400
PASTED_RE = re.compile(r"<pasted_content[^>]*>\n?(.*?)\n?</pasted_content[^>]*>", re.S)
KNOWN_TAGS = frozenset({"task-notification", "command-name", "command-message", "local-command-stdout",
                        "local-command-caveat", "system-reminder", "bash-input", "bash-stdout", "pasted_content",
                        "user-prompt-submit-hook", "ide_opened_file", "ide_selection"})
LINE_EDGES = (0, 5, 10, 11, 20, 50, 100, 500, 1000, 10**9)
TYPE_RE = re.compile(rb'"type"\s*:\s*"([^"]+)"')


class CorpusMissing(Exception):
    pass


def resolve_corpus(arg: Optional[str]) -> Path:
    root = Path(os.path.realpath(os.path.expanduser(arg or "~/.claude/projects")))
    if not root.is_dir():
        raise CorpusMissing("corpus root is not a directory: %s" % root)
    return root


def iter_transcripts(root: Path) -> Iterator[Tuple[str, int, float]]:
    seen = set()
    for dirpath, _dirs, names in os.walk(root):
        for name in sorted(names):
            if not name.endswith(".jsonl"):
                continue
            real = os.path.realpath(os.path.join(dirpath, name))
            if real in seen:
                continue
            seen.add(real)
            try:
                st = os.stat(real)
            except OSError:
                continue
            yield real, st.st_size, st.st_mtime


def record_key(obj: Dict[str, Any]) -> str:
    att = obj.get("attachment")
    att_type = att.get("type") if isinstance(att, dict) else ""
    sub = obj.get("subtype")
    return "%s|%s|%s" % (obj.get("type", ""), sub if isinstance(sub, str) else "", att_type or "")


def message_blocks(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def prompt_text(obj: Dict[str, Any]) -> Optional[str]:
    if obj.get("type") == "attachment":
        att = obj.get("attachment") or {}
        if att.get("type") == "queued_command":
            p = att.get("prompt")
            return p if isinstance(p, str) else None
        return None
    if obj.get("type") != "user" or obj.get("isMeta"):
        return None
    blocks = message_blocks(obj)
    if not blocks or any(b.get("type") == "tool_result" for b in blocks):
        return None
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def norm_forms(text: str) -> Tuple[str, ...]:
    lf = text.replace("\r\n", "\n").replace("\r", "\n")
    trimmed = "\n".join(line.rstrip() for line in lf.split("\n")).strip()
    unwrapped = PASTED_RE.sub(lambda m: m.group(1), trimmed).strip()
    unwrapped = "\n".join(line.rstrip() for line in unwrapped.split("\n"))
    return text, lf, trimmed, unwrapped, " ".join(unwrapped.split())


FORM_NAMES = ("raw", "crlf", "trailing_blanks", "unwrapped", "whitespace_collapsed")


def digest(text: str) -> bytes:
    return hashlib.blake2b(text.encode("utf-8", "replace"), digest_size=8).digest()


class FileScan:

    def __init__(self) -> None:
        self.queue: List[Tuple[int, str, Optional[List[bytes]], str]] = []
        self.prompts: List[Dict[bytes, List[int]]] = [collections.defaultdict(list) for _ in FORM_NAMES]


def bucket_of(value: int, edges: Tuple[int, ...] = LENGTH_EDGES) -> int:
    return bisect.bisect_right(edges, value) - 1


class Census:

    def __init__(self) -> None:
        self.files: Counter[str] = collections.Counter()
        self.keys: Counter[str] = collections.Counter()
        self.user_shapes: Counter[str] = collections.Counter()
        self.sidechain_user: Counter[str] = collections.Counter()
        self.entrypoints: Counter[str] = collections.Counter()
        self.blocks: Counter[str] = collections.Counter()
        self.stops: Counter[str] = collections.Counter()
        self.tools: Counter[str] = collections.Counter()
        self.queue_ops: Counter[str] = collections.Counter()
        self.queue_fate: Counter[str] = collections.Counter()
        self.pairing: Counter[str] = collections.Counter()
        self.oversize_lines = 0
        self.oversize_max_bytes = 0
        self.oversize_by_type: Counter[str] = collections.Counter()
        self.length: List[List[int]] = [[0, 0] for _ in LENGTH_EDGES[:-1]]
        self.lines_len: List[List[int]] = [[0, 0] for _ in LINE_EDGES[:-1]]
        self.wrapped_inner: Dict[str, Optional[int]] = {"min_chars": None, "max_unwrapped_chars": 0, "min_lines": None,
                              "max_unwrapped_lines": 0, "wrapped_prompts": 0}
        self.by_version: Dict[str, List[int]] = collections.defaultdict(lambda: [0, 0])
        self.preview_sum = 0
        self.preview_n = 0
        self.mtimes: List[float] = []
        self.basenames: Counter[str] = collections.Counter()
        self.bad_json = 0

    def tally_prompt(self, text: str, version: str = "?") -> None:
        wrapped = "<pasted_content" in text
        if wrapped or text.count("\n") >= 9:
            self.by_version[version][0 if wrapped else 1] += 1
        self.length[bucket_of(len(text))][1 if wrapped else 0] += 1
        self.lines_len[bucket_of(text.count("\n") + 1, LINE_EDGES)][1 if wrapped else 0] += 1
        self.preview_sum += min(len(text), 200)
        self.preview_n += 1
        w = self.wrapped_inner
        if wrapped:
            w["wrapped_prompts"] = (w["wrapped_prompts"] or 0) + 1
            for m in PASTED_RE.finditer(text):
                n, ln = len(m.group(1)), m.group(1).count("\n") + 1
                w["min_chars"] = n if w["min_chars"] is None else min(w["min_chars"], n)
                w["min_lines"] = ln if w["min_lines"] is None else min(w["min_lines"], ln)
        elif not text.lstrip().startswith("<"):
            w["max_unwrapped_chars"] = max(w["max_unwrapped_chars"] or 0, len(text))
            w["max_unwrapped_lines"] = max(w["max_unwrapped_lines"] or 0, text.count("\n") + 1)

    def tally_assistant(self, blocks: List[Dict[str, Any]], obj: Dict[str, Any]) -> None:
        for b in blocks:
            self.blocks["assistant:%s" % b.get("type")] += 1
            if b.get("type") == "tool_use":
                name = b.get("name") or "?"
                self.tools["mcp:*" if name.startswith("mcp__") else name] += 1
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        self.stops[str(msg.get("stop_reason"))] += 1

    def tally_user(self, obj: Dict[str, Any], text: Optional[str]) -> None:
        blocks = message_blocks(obj)
        for b in blocks:
            self.blocks["user:%s" % b.get("type")] += 1
        shapes = self.sidechain_user if obj.get("isSidechain") else self.user_shapes
        if obj.get("isCompactSummary"):
            shapes["compact_summary"] += 1
        elif obj.get("isMeta"):
            shapes["meta"] += 1
        elif text is None:
            shapes["tool_result"] += 1
        elif text.lstrip().startswith("<"):
            word = (re.match(r"\s*<([\w-]+)", text) or [0, "?"])[1]
            shapes["tagged:" + (word if word in KNOWN_TAGS else "other")] += 1
        elif text.startswith("[Request interrupted by user"):
            shapes["interrupt"] += 1
        else:
            shapes["plain_prompt"] += 1

    def scan_record(self, obj: Dict[str, Any], idx: int, scan: FileScan) -> None:
        self.keys[record_key(obj)] += 1
        if "entrypoint" in obj:
            self.entrypoints[str(obj["entrypoint"])] += 1
        kind = obj.get("type")
        text = prompt_text(obj)
        if kind == "user":
            self.tally_user(obj, text)
        elif kind == "assistant":
            self.tally_assistant(message_blocks(obj), obj)
        if text is not None and not obj.get("isSidechain"):
            if kind == "user":
                self.tally_prompt(text, str(obj.get("version")))
            for form, h in zip(scan.prompts, [digest(f) for f in norm_forms(text)]):
                form[h].append(idx)
        if kind == "queue-operation":
            op = obj.get("operation")
            self.queue_ops[str(op)] += 1
            content = obj.get("content")
            hashes = [digest(f) for f in norm_forms(content)] if isinstance(content, str) else None
            shape = "tagged" if isinstance(content, str) and content.lstrip().startswith("<") else "plain"
            scan.queue.append((idx, str(op), hashes, shape))

    def finish_queue(self, scan: FileScan) -> None:
        pending: List[Tuple[int, List[bytes]]] = []
        for idx, op, hashes, shape in scan.queue:
            if op == "enqueue" and hashes:
                pending.append((idx, hashes))
                self.pairing_for(scan, idx, hashes, shape)
            elif op == "dequeue":
                self.queue_fate["dequeue_popped_head" if pending else "dequeue_on_empty"] += 1
                if pending:
                    pending.pop(0)
            elif op == "remove":
                self.remove_fate(scan, idx, hashes, shape, pending)
            elif op == "popAll":
                self.queue_fate["popAll_cleared_%d" % min(len(pending), 3)] += 1
                pending.clear()
        self.queue_fate["pending_at_eof"] += len(pending)

    def pairing_for(self, scan: FileScan, idx: int, hashes: List[bytes], shape: str) -> None:
        for name, forms, h in zip(FORM_NAMES, scan.prompts, hashes):
            after = [i for i in forms.get(h, ()) if idx < i <= idx + PAIR_WINDOW]
            if after:
                self.pairing["%s_equal_at_%s" % (shape, name)] += 1
                return
        self.pairing["%s_no_prompt_record_equal" % shape] += 1

    def remove_fate(self, scan: FileScan, idx: int, hashes: Optional[List[bytes]], shape: str,
                    pending: List[Tuple[int, List[bytes]]]) -> None:
        if hashes is None:
            self.queue_fate["remove_no_content"] += 1
            if pending:
                pending.pop(0)
            return
        self.queue_fate["remove_with_content_" + shape] += 1
        match = next((n for n, (_i, hs) in enumerate(pending) if hs[2] == hashes[2]), None)
        self.queue_fate["remove_matches_pending" if match is not None else "remove_matches_nothing"] += 1
        if match is not None:
            pending.pop(match)
        later = any(idx < i <= idx + PAIR_WINDOW for i in scan.prompts[4].get(hashes[4], ()))
        earlier = any(i < idx for i in scan.prompts[4].get(hashes[4], ()))
        self.queue_fate["remove_%s_text_becomes_prompt_after" % shape if later else
                        "remove_%s_text_never_prompted_after" % shape] += 1
        self.queue_fate["remove_%s_text_prompted_before" % shape if earlier else
                        "remove_%s_text_not_prompted_before" % shape] += 1

    def scan_file(self, path: str, size: int, mtime: float) -> None:
        kind = "subagent" if "/subagents/" in path else "main"
        self.files[kind] += 1
        self.files["bytes"] += size
        self.mtimes.append(mtime)
        self.basenames[os.path.basename(path)] += 1
        scan = FileScan()
        try:
            self.read_file(path, scan)
        except OSError:
            self.files["vanished_or_unreadable"] += 1
            return
        self.finish_queue(scan)

    def read_file(self, path: str, scan: FileScan) -> None:
        idx = 0
        with open(path, "rb") as fh:
            for raw in fh:
                idx += 1
                if len(raw) > MAX_PARSE_BYTES:
                    m = TYPE_RE.search(raw[:OVERSIZE_PREFIX])
                    self.oversize_lines += 1
                    self.oversize_max_bytes = max(self.oversize_max_bytes, len(raw))
                    self.oversize_by_type[m.group(1).decode() if m else "?"] += 1
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    self.bad_json += 1
                    continue
                if isinstance(obj, dict):
                    self.scan_record(obj, idx, scan)


def index_counts(c: Census) -> IndexCounts:
    marker_keys = ("system|compact_boundary|", "system|microcompact_boundary|", "continued-in||",
                   "history-suppression||")
    return IndexCounts(
        plain_prompts=c.user_shapes["plain_prompt"],
        tagged_prompts=sum(v for k, v in c.user_shapes.items() if k.startswith("tagged:")),
        queued_commands=c.keys["attachment||queued_command"],
        agent_launches=c.tools["Agent"] + c.tools["Task"], subagent_files=c.files["subagent"],
        marker_records=sum(c.keys[k] for k in marker_keys), todo_writes=c.tools["TodoWrite"],
        main_files=c.files["main"], transcript_bytes=c.files["bytes"])


def build_report(c: Census, elapsed: float, complete: bool, settings: Optional[str]) -> Dict[str, Any]:
    mean = c.preview_sum / max(1, c.preview_n)
    edges = list(LENGTH_EDGES)
    return {
        "complete": complete, "elapsed_seconds": round(elapsed, 1), "files": dict(c.files),
        "duplicate_basenames": sum(1 for n in c.basenames.values() if n > 1),
        "bad_json_lines": c.bad_json, "oversize_lines": {"lines": c.oversize_lines, "max_bytes": c.oversize_max_bytes,
                                                          "by_type": dict(c.oversize_by_type)},
        "record_keys": dict(c.keys.most_common()), "user_shapes": dict(c.user_shapes.most_common()),
        "sidechain_user_shapes": dict(c.sidechain_user.most_common()), "entrypoints": dict(c.entrypoints.most_common()),
        "blocks": dict(c.blocks.most_common()), "stop_reasons": dict(c.stops.most_common()),
        "tools_top": dict(c.tools.most_common(25)), "queue_operations": dict(c.queue_ops),
        "queue_fate": dict(c.queue_fate), "enqueue_to_prompt_equality": dict(c.pairing),
        "prompt_length_buckets": [{"from": edges[i], "to": edges[i + 1], "unwrapped": a, "wrapped": b}
                                  for i, (a, b) in enumerate(c.length)],
        "prompt_line_buckets": [{"from": LINE_EDGES[i], "to": LINE_EDGES[i + 1], "unwrapped": a, "wrapped": b}
                                for i, (a, b) in enumerate(c.lines_len)],
        "pasted_content": c.wrapped_inner,
        "wrapped_vs_long_unwrapped_by_version": {k: v for k, v in sorted(c.by_version.items())},
        "preview_mean_chars": round(mean, 1),
        "index_projection": project_index(index_counts(c), probe_row_bytes(mean)),
        "cleanup": cleanup_evidence(c.mtimes, settings),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", help="transcript root (default: realpath of ~/.claude/projects)")
    ap.add_argument("--max-seconds", type=float, default=0, help="stop scanning after this long (0 = no limit)")
    ap.add_argument("--limit-files", type=int, default=0, help="scan at most this many files (0 = all)")
    ap.add_argument("--settings", help="settings.json to read cleanupPeriodDays from")
    ap.add_argument("--out", help="also write the JSON report to this file")
    args = ap.parse_args(argv)
    try:
        root = resolve_corpus(args.corpus)
        files = iter_transcripts(root)
        first = next(files, None)
        if first is None:
            raise CorpusMissing("no .jsonl transcript under %s" % root)
    except CorpusMissing as exc:
        print("census: could not run: %s" % exc, file=sys.stderr)
        return EXIT_COULD_NOT_RUN
    census, start, complete, scanned = Census(), time.time(), True, 0
    for path, size, mtime in itertools.chain([first], files):
        if (args.limit_files and scanned >= args.limit_files) or (
                args.max_seconds and time.time() - start > args.max_seconds):
            complete = False
            break
        census.scan_file(path, size, mtime)
        scanned += 1
    text = json.dumps(build_report(census, time.time() - start, complete, args.settings), indent=1, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

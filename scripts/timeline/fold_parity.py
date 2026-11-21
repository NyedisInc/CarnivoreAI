#!/usr/bin/env python3
"""Read-only parity of the timeline fold against the legacy transcript readers, on real transcripts (T2 acceptance).

Its one job: fold real main transcripts and compare ``facts_from_state`` with the legacy reader field by field.
Three checks:

- ``whole``: per file, the fold over the whole file against ``read_transcript_facts`` with a window the size of the file
  (EVERY field), and the production-shaped answer (``size=``: narrow window, widening, contract, MCP history) against
  ``read_transcript_facts`` as production calls it (every field except ``TURN_END_FIELDS``).
- ``cuts``: the same production-shaped comparison at many cut points of each file, the way a live file looks while it is
  written: the fold is read at the end of a line, and a COPY of the file truncated to that byte is read by the legacy
  reader (so window opening, the 4 MiB re-read, the shape contract and the MCP history join are the real ones).

- ``ascending``: the steady state of the live 2-second cycle. A COPY of the file is grown in chunks and the legacy reader reads
  it after each chunk WITHOUT ``reset_history()`` in between (its per-file MCP cache accumulates), while the fold, read at the
  same size, accumulates its own model of that cache. Every pass is compared, the MCP events (and the health verdict read off
  them) included. ``--mode all`` runs the three.

It prints one JSON document of counts and field names, never transcript text, never writes into the corpus (cuts work on
a temp copy). Exit codes: 0 no mismatch, 1 a mismatch (counts say which fields), 2 could not run (corpus absent or no
file; never a pass).

Usage:
    python3 scripts/timeline/fold_parity.py [--mode whole|cuts|ascending|both|all] [--corpus DIR] [--newest N]
        [--cuts K] [--step BYTES] [--min-bytes B] [--max-bytes B] [--max-seconds S]
Default corpus: realpath of ~/.claude/projects.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Counter, Dict, FrozenSet, Iterator, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from census import CorpusMissing, resolve_corpus  # noqa: E402
from placement import newest_main_transcripts  # noqa: E402
from src.core.attention.transcript_facts import (  # noqa: E402
    FACTS_TAIL_BYTES,
    FACTS_WIDE_TAIL_BYTES,
    TranscriptFacts,
    read_transcript_facts,
)
from src.core.mcp_health.fold import fold_mcp_health  # noqa: E402
from src.core.mcp_health.history import reset_history  # noqa: E402
from src.core.timeline.context import ExtractContext  # noqa: E402
from src.core.timeline.extract import MAX_LINE_BYTES, extract_line  # noqa: E402
from src.core.timeline.facts_adapter import TURN_END_FIELDS, facts_from_state  # noqa: E402
from src.core.timeline.facts_window import choose_window, tail_bounds  # noqa: E402
from src.core.timeline.fold import ConvState, fold_record  # noqa: E402
from src.core.timeline.stamps import WINDOW_RETENTION_BYTES  # noqa: E402

EXIT_OK, EXIT_MISMATCH, EXIT_COULD_NOT_RUN = 0, 1, 2
QUIET_SECONDS = 600
NO_SKIP: FrozenSet[str] = frozenset()


def differing_fields(got: TranscriptFacts, want: TranscriptFacts, skip: FrozenSet[str]) -> List[str]:
    return [f.name for f in dataclasses.fields(TranscriptFacts)
            if f.name not in skip and getattr(got, f.name) != getattr(want, f.name)]


def turn_end_skip(want: TranscriptFacts) -> FrozenSet[str]:
    return TURN_END_FIELDS if want.turn_end_kind is None or want.turn_end_outside_window else NO_SKIP


def fold_lines(path: str, conv: str, retain_bytes: Optional[int] = WINDOW_RETENTION_BYTES) -> Iterator[Tuple[ConvState, int]]:
    state, ctx, offset = ConvState(conv=conv, retain_bytes=retain_bytes), ExtractContext(conv=conv), 0
    with open(path, "rb") as handle:
        for raw in handle:
            offset += len(raw)
            body = raw.rstrip(b"\n")
            try:
                record = json.loads(body) if body else None
            except ValueError:
                record = None
            serial = "sha256:" + hashlib.sha256(body).hexdigest() if len(body) > MAX_LINE_BYTES else None
            fold_record(state, record, extract_line(ctx, body, offset, serial=serial) if body else [], offset)
            yield state, offset


def check_whole(path: str, now: datetime, counts: Counter[str], examples: Dict[str, List[str]]) -> None:
    size = os.path.getsize(path)
    state = whole_state = None
    for state, _end in fold_lines(path, Path(path).stem):
        pass
    for whole_state, _end in fold_lines(path, Path(path).stem, retain_bytes=None):
        pass
    if state is None or whole_state is None or state.cursor != size:
        counts["skipped_torn_or_empty"] += 1
        return
    reset_history()
    whole = read_transcript_facts(path, tail_bytes=size + 1, wide_tail_bytes=size + 1, now=now)
    reset_history()
    prod = read_transcript_facts(path, now=now)
    counts["files"] += 1
    for label, got, want, skip in (("whole", facts_from_state(whole_state, now=now, fresh_history=True), whole, NO_SKIP),
                                   ("production", facts_from_state(state, now=now, size=size, fresh_history=True), prod,
                                    turn_end_skip(prod))):
        names = differing_fields(got, want, skip)
        if names:
            counts[label + "_files_bad"] += 1
            counts.update(label + ":" + name for name in names)
            examples[label].append(Path(path).name[:8] + " " + ",".join(names))


def check_cuts(path: str, cuts: int, now: datetime, tmp_dir: str, counts: Counter[str], examples: Dict[str, List[str]]) -> None:
    total = os.path.getsize(path)
    targets = sorted({int(total * (i + 1) / (cuts + 1)) for i in range(cuts)})
    got: Dict[int, TranscriptFacts] = {}
    pending = list(targets)
    for state, end in fold_lines(path, Path(path).stem):
        while pending and end >= pending[0]:
            pending.pop(0)
            got[end] = facts_from_state(state, now=now, size=end, fresh_history=True)
            if choose_window(state, end).bound != tail_bounds(state, end, FACTS_TAIL_BYTES, FACTS_WIDE_TAIL_BYTES)[0]:
                counts["cuts_widened"] += 1
    copy = os.path.join(tmp_dir, "cut.jsonl")
    shutil.copyfile(path, copy)
    for end in sorted(got, reverse=True):
        os.truncate(copy, end)
        reset_history()
        want = read_transcript_facts(copy, now=now)
        names = differing_fields(got[end], want, turn_end_skip(want))
        counts["cuts"] += 1
        if names:
            counts["cuts_bad"] += 1
            counts.update("cut:" + name for name in names)
            if len(examples["cut"]) < 20:
                examples["cut"].append(Path(path).name[:8] + "@" + str(end) + " " + ",".join(names))


def check_ascending(path: str, step: int, now: datetime, tmp_dir: str, counts: Counter[str], examples: Dict[str, List[str]]) -> None:
    copy = os.path.join(tmp_dir, "live.jsonl")
    open(copy, "wb").close()
    reset_history()
    written, next_at = 0, step
    counts["ascending_files"] += 1
    with open(path, "rb") as source:
        for state, end in fold_lines(path, Path(path).stem):
            if end < next_at:
                continue
            next_at = end + step
            with open(copy, "ab") as out:
                source.seek(written)
                out.write(source.read(end - written))
                written = end
            want = read_transcript_facts(copy, now=now)
            got = facts_from_state(state, now=now, size=end)
            names = differing_fields(got, want, turn_end_skip(want))
            counts["ascending_passes"] += 1
            counts["ascending_passes_with_mcp_events"] += bool(want.mcp_events)
            counts["ascending_passes_with_heal"] += any(e.reconnect and not e.exact for e in want.mcp_events)
            if fold_mcp_health(got.mcp_events, window_from=got.mcp_window_from) != fold_mcp_health(
                    want.mcp_events, window_from=want.mcp_window_from):
                counts["ascending_health_differs"] += 1
            if names:
                counts["ascending_bad"] += 1
                counts.update("ascending:" + name for name in names)
                if len(examples["ascending"]) < 20:
                    examples["ascending"].append(Path(path).name[:8] + "@" + str(end) + " " + ",".join(names))


def run(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    try:
        root = resolve_corpus(args.corpus)
    except CorpusMissing as exc:
        return EXIT_COULD_NOT_RUN, {"could_not_run": str(exc)}
    now = datetime.now(timezone.utc)
    quiet = [p for p in newest_main_transcripts(root, args.newest * 4)
             if time.time() - os.path.getmtime(p) > QUIET_SECONDS and args.min_bytes <= os.path.getsize(p) <= args.max_bytes]
    files = quiet[: args.newest]
    if not files:
        return EXIT_COULD_NOT_RUN, {"could_not_run": "no quiet main transcript of the asked size under %s" % root}
    counts: Counter[str] = collections.Counter()
    examples: Dict[str, List[str]] = collections.defaultdict(list)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="fold-parity-") as tmp_dir:
        for path in files:
            if time.monotonic() - started > args.max_seconds:
                counts["stopped_at_time_cap"] = 1
                break
            if args.mode in ("whole", "both", "all"):
                check_whole(path, now, counts, examples)
            if args.mode in ("cuts", "both", "all"):
                check_cuts(path, args.cuts, now, tmp_dir, counts, examples)
            if args.mode in ("ascending", "all"):
                check_ascending(path, args.step, now, tmp_dir, counts, examples)
    bad = sum(v for k, v in counts.items() if k in ("whole_files_bad", "production_files_bad", "cuts_bad", "ascending_bad", "ascending_health_differs"))
    return (EXIT_MISMATCH if bad else EXIT_OK), {"files_asked": len(files), "counts": dict(counts), "examples": examples}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mode", choices=("whole", "cuts", "ascending", "both", "all"), default="both",
                        help="both is whole plus cuts; all adds ascending")
    parser.add_argument("--corpus", help="transcript root (default ~/.claude/projects)")
    parser.add_argument("--newest", type=int, default=60, help="how many newest quiet main transcripts")
    parser.add_argument("--cuts", type=int, default=25, help="cut points per file (cuts mode)")
    parser.add_argument("--step", type=int, default=64 * 1024, help="bytes between two passes (ascending mode)")
    parser.add_argument("--min-bytes", type=int, default=0)
    parser.add_argument("--max-bytes", type=int, default=40_000_000)
    parser.add_argument("--max-seconds", type=float, default=900.0, help="wall-clock cap")
    code, report = run(parser.parse_args(argv))
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())

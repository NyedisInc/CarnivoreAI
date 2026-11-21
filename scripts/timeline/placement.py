#!/usr/bin/env python3
"""Read-only placement measurement of the timeline extractor over the newest real transcripts (T1 carry-over).

Its one job: run ``extract_line`` over the newest main transcripts of a corpus and check where events sit. Two claims
from the plan (docs/timeline.md section 9): every main-thread ``reply`` sits inside a turn (its ``turn`` is set and is
not after the reply), and every turn's primary ``turn_end`` follows the turn's answer (no ``reply`` of the turn lands
after the primary end, except a later record of the very message that closed it, which the extractor keeps in the
turn on purpose). It prints one JSON document of counts, never transcript text, and never writes into the corpus.

Exit codes: 0 both claims hold, 1 a claim failed (counts say which), 2 could not run (corpus absent or empty; never a
pass).

Usage:
    python3 scripts/timeline/placement.py [--corpus DIR] [--newest N] [--max-seconds S]
Default corpus: realpath of ~/.claude/projects; default N 200 (main transcripts only, not sub-agent files).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from census import CorpusMissing, iter_transcripts, resolve_corpus  # noqa: E402
from src.core.timeline.context import ExtractContext  # noqa: E402
from src.core.timeline.extract import MAX_LINE_BYTES, extract_line  # noqa: E402
from src.core.timeline.extract_message import END_MAX_TOKENS  # noqa: E402
from src.core.timeline.model import Kind, TimelineEvent  # noqa: E402

EXIT_OK, EXIT_CLAIM_FAILED, EXIT_COULD_NOT_RUN = 0, 1, 2
DEFAULT_NEWEST = 200
SUBAGENT_DIR = "subagents"


def newest_main_transcripts(root: Path, count: int) -> List[str]:
    found = [(mtime, path) for path, _size, mtime in iter_transcripts(root) if SUBAGENT_DIR not in Path(path).parts]
    return [path for _mtime, path in sorted(found, reverse=True)[:count]]


def events_of_file(path: str) -> List[TimelineEvent]:
    ctx, offset, events = ExtractContext(conv=Path(path).stem), 0, []
    with open(path, "rb") as handle:
        for raw in handle:
            offset += len(raw)
            line = raw.rstrip(b"\n")
            serial: Optional[str] = "sha256:" + hashlib.sha256(line).hexdigest() if len(line) > MAX_LINE_BYTES else None
            events.extend(extract_line(ctx, line, offset, serial=serial))
    return events


def order(event: TimelineEvent) -> Tuple[int, int]:
    return event.pos.offset, event.n


def reopened_by_cause(end: TimelineEvent, closing: Optional[str], calls: List[TimelineEvent]) -> bool:
    if end.data.get("end") == END_MAX_TOKENS:
        return True
    return any(call.msg and call.msg == closing and order(call) > order(end) for call in calls)


def measure_events(events: List[TimelineEvent], counts: Dict[str, int]) -> None:
    ends: Dict[int, TimelineEvent] = {}
    line_msg: Dict[int, str] = {}
    calls: Dict[int, List[TimelineEvent]] = {}
    replies: Dict[int, List[TimelineEvent]] = {}
    turns = set()
    for event in events:
        if event.thread != "main":
            continue
        if event.turn is not None:
            turns.add(event.turn)
        if event.msg:
            line_msg.setdefault(event.pos.offset, event.msg)
        if event.kind is Kind.TOOL_CALL and event.turn is not None:
            calls.setdefault(event.turn, []).append(event)
        if event.kind is Kind.TURN_END and event.turn is not None and not event.data.get("merged"):
            ends.setdefault(event.turn, event)
        if event.kind is Kind.REPLY:
            counts["replies"] += 1
            if event.turn is None:
                counts["replies_outside_turn"] += 1
            elif event.turn > event.pos.offset:
                counts["replies_before_their_turn"] += 1
            else:
                replies.setdefault(event.turn, []).append(event)
    counts["turns"] += len(turns)
    counts["turns_with_end"] += len(ends)
    for turn, end in ends.items():
        closing = line_msg.get(end.pos.offset)
        for reply in replies.get(turn, []):
            if order(reply) > order(end):
                counts["replies_after_primary_end"] += 1
                counts["replies_after_primary_end_of_closing_message"] += bool(closing and reply.msg == closing)
                counts["replies_after_primary_end_in_reopened_turn"] += bool(
                    not (closing and reply.msg == closing) and reopened_by_cause(end, closing, calls.get(turn, [])))


def unexplained(counts: Dict[str, int]) -> int:
    return (counts["replies_outside_turn"] + counts["replies_before_their_turn"] + counts["replies_after_primary_end"]
            - counts["replies_after_primary_end_of_closing_message"] - counts["replies_after_primary_end_in_reopened_turn"])


def run(corpus: Optional[str], newest: int, max_seconds: float) -> Tuple[int, Dict[str, Any]]:
    try:
        root = resolve_corpus(corpus)
    except CorpusMissing as exc:
        return EXIT_COULD_NOT_RUN, {"could_not_run": str(exc)}
    files = newest_main_transcripts(root, newest)
    if not files:
        return EXIT_COULD_NOT_RUN, {"could_not_run": "no main transcript under %s" % root}
    counts = {key: 0 for key in ("replies", "replies_outside_turn", "replies_before_their_turn", "turns",
                                 "turns_with_end", "replies_after_primary_end",
                                 "replies_after_primary_end_of_closing_message",
                                 "replies_after_primary_end_in_reopened_turn")}
    started, done = time.monotonic(), 0
    for path in files:
        if time.monotonic() - started > max_seconds:
            break
        try:
            measure_events(events_of_file(path), counts)
            done += 1
        except OSError as exc:
            counts["files_unreadable"] = counts.get("files_unreadable", 0) + 1
            print("skipped %s: %s" % (Path(path).name, exc.strerror or exc), file=sys.stderr)
    report: Dict[str, Any] = {"files_asked": len(files), "files_measured": done, **counts}
    failed = unexplained(counts) > 0
    if done < len(files):
        report["stopped_at_time_cap"] = True
    return (EXIT_CLAIM_FAILED if failed else EXIT_OK), report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--corpus", help="transcript root (default ~/.claude/projects)")
    parser.add_argument("--newest", type=int, default=DEFAULT_NEWEST, help="how many newest main transcripts")
    parser.add_argument("--max-seconds", type=float, default=600.0, help="wall-clock cap")
    args = parser.parse_args(argv)
    code, report = run(args.corpus, args.newest, args.max_seconds)
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""skip-audit.py - make pytest skips visible, and fail the ones that hide.

Why this exists
---------------
A suite that reports "passed" while quietly skipping the tests that would
have failed is the false-green pattern this project keeps paying for. A
skip is the legitimate third outcome (could-not-evaluate), but only while
somebody can see it and only while the test still runs SOMEWHERE. A test
skipped on every platform CI runs is furniture: it can never go red, so
it is not a measurement.

Two subcommands:

  report <junit.xml> --ids-out <file>
      Print the skip count and every skipped test id with its reason,
      and write the sorted ids one per line for the intersect step.
      Always exits 0 - reporting is not judging.

  intersect <ids-file> [<ids-file> ...] --require 2 [--exempt <file>]
      Fail (exit 1) when a test id was skipped in EVERY input file, i.e.
      on every platform in the matrix. Also fails when fewer than
      --require files were supplied, because an intersection over one
      platform's list would pass trivially and prove nothing.

      AN EXEMPTION IS NOT A SILENCER. Every exempted id is PRINTED with
      the reason it was let through, so it stays in front of whoever
      reads the job, and a pattern that matches NOTHING fails the build.
      A stale exemption is the same defect as a stale skip: a line that
      says a test is covered by an excuse it no longer needs, sitting
      where the next person will trust it.

Example:
    python3 scripts/ci/skip-audit.py report junit.xml --ids-out skips.txt
    python3 scripts/ci/skip-audit.py intersect a.txt b.txt --require 2 \
        --exempt scripts/ci/skip-audit-exempt.txt
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple


def _read_skips(junit_path: Path) -> Dict[str, str]:
    if not junit_path.is_file():
        sys.exit(f"skip-audit: {junit_path} does not exist - pytest wrote no "
                 "report, so the skip count CANNOT BE DETERMINED")
    try:
        tree = ET.parse(junit_path)
    except ET.ParseError as exc:
        sys.exit(f"skip-audit: {junit_path} did not parse ({exc}) - the skip "
                 "count CANNOT BE DETERMINED")

    skips: Dict[str, str] = {}
    for case in tree.iter("testcase"):
        skipped = case.find("skipped")
        if skipped is None:
            continue
        test_id = f"{case.get('classname', '?')}::{case.get('name', '?')}"
        skips[test_id] = (skipped.get("message") or "").strip().replace("\n", " ")
    return skips


def _read_exemptions(path: Path) -> List[Tuple[str, str]]:
    if not path.is_file():
        sys.exit(f"skip-audit: {path} does not exist - the exemption list "
                 "was named but cannot be read, so which skips are "
                 "permitted CANNOT BE DETERMINED")
    entries: List[Tuple[str, str]] = []
    for line in path.read_text().splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        pattern, _, reason = text.partition("#")
        entries.append((pattern.strip(), reason.strip() or "(no reason given)"))
    return entries


def _matches(pattern: str, test_id: str) -> bool:
    expr = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.fullmatch(expr, test_id) is not None


def _cmd_report(args: argparse.Namespace) -> int:
    skips = _read_skips(Path(args.junit))
    label = args.label or "this run"
    print(f"skip-audit: {len(skips)} skipped test(s) on {label}")
    for test_id in sorted(skips):
        reason = skips[test_id] or "(no reason given)"
        print(f"  SKIP {test_id}: {reason[:300]}")
    if args.ids_out:
        Path(args.ids_out).write_text("\n".join(sorted(skips)) + "\n")
    return 0


def _cmd_intersect(args: argparse.Namespace) -> int:
    files: List[Path] = [Path(f) for f in args.ids_files]
    if len(files) < args.require:
        print(
            f"skip-audit: FAIL - {len(files)} skip list(s) supplied but "
            f"--require {args.require}. An intersection over fewer lists "
            "than platforms cannot prove a test ran anywhere.",
            file=sys.stderr,
        )
        return 1

    sets = []
    for path in files:
        if not path.is_file():
            print(f"skip-audit: FAIL - {path} missing; a platform's skip list "
                  "did not arrive, so 'skipped everywhere' CANNOT BE "
                  "DETERMINED.", file=sys.stderr)
            return 1
        sets.append({line.strip() for line in path.read_text().splitlines()
                     if line.strip()})

    everywhere = sorted(set.intersection(*sets))

    exemptions = _read_exemptions(Path(args.exempt)) if args.exempt else []
    matched: Dict[str, List[str]] = {pattern: [] for pattern, _ in exemptions}
    unexcused: List[str] = []
    for test_id in everywhere:
        hit = next(
            (p for p, _ in exemptions if _matches(p, test_id)), None
        )
        if hit is None:
            unexcused.append(test_id)
        else:
            matched[hit].append(test_id)

    if exemptions:
        excused = sum(len(ids) for ids in matched.values())
        print(f"skip-audit: {excused} skipped-everywhere test(s) are "
              f"EXEMPT by {args.exempt}:")
        for pattern, reason in exemptions:
            for test_id in matched[pattern]:
                print(f"  EXEMPT {test_id}: {reason}")

    stale = [(p, r) for p, r in exemptions if not matched[p]]
    if stale:
        print(f"skip-audit: FAIL - {len(stale)} exemption(s) in "
              f"{args.exempt} matched no skipped-everywhere test:",
              file=sys.stderr)
        for pattern, reason in stale:
            print(f"  STALE EXEMPTION {pattern}: {reason}", file=sys.stderr)
        print("The test now runs somewhere, or it is gone. Delete the line.",
              file=sys.stderr)
        return 1

    everywhere = unexcused
    if not everywhere:
        print(f"skip-audit: OK - no unexempted test was skipped on all "
              f"{len(files)} platforms.")
        return 0

    print(f"skip-audit: FAIL - {len(everywhere)} test(s) were skipped on ALL "
          f"{len(files)} platforms, so they were never measured anywhere:",
          file=sys.stderr)
    for test_id in everywhere:
        print(f"  NEVER RAN {test_id}", file=sys.stderr)
    print("Either give the test an environment where it can run, or delete "
          "it. A test that cannot go red is not a test.", file=sys.stderr)
    return 1


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    rep = sub.add_parser("report", help="print and dump this run's skips")
    rep.add_argument("junit")
    rep.add_argument("--ids-out")
    rep.add_argument("--label")
    rep.set_defaults(func=_cmd_report)

    inter = sub.add_parser("intersect", help="fail on skipped-everywhere tests")
    inter.add_argument("ids_files", nargs="+")
    inter.add_argument("--require", type=int, default=2)
    inter.add_argument(
        "--exempt",
        help="file of patterns for skips CI cannot supply an environment for",
    )
    inter.set_defaults(func=_cmd_intersect)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

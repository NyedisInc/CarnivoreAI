#!/usr/bin/env python3
"""Backfill the lineage graph from the transcripts on disk. DRY RUN BY DEFAULT; idempotent; one implementation.

    python3 scripts/lineage/backfill_disk.py                  # dry run: reads only, prints what it would add
    python3 scripts/lineage/backfill_disk.py --apply          # write it (take a verified backup first)
    python3 scripts/lineage/backfill_disk.py --db copy.db --state-dir /tmp/state --corpus /path/to/projects

It is the SAME code as the daemon's live pass (``src/core/lineage/live.py``): node levels from each head's
entrypoint (the conversations that never got a node), compact boundaries as milestones, ``forkedFrom`` split
points on fork edges, subagent edges, codex rollouts' parent pointers (``forked_from_id``, ``parent_thread_id``), stored ``switch`` flips reclassified when the new transcript proves a
``clear`` or ``fork``, and ``spawned_by`` edges. A rerun adds nothing. The dry run opens the datastore
``mode=ro`` and does not touch the cursor. ``--apply`` also advances the cursor file in the state directory.
Exit 2: no datastore or one before schema v49; 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.lineage import live  # noqa: E402


def main(argv=None) -> int:
    from src.config import settings
    from src.core.db import db_path_for

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, help="datastore (default: the live one)")
    parser.add_argument("--state-dir", type=Path, help="where the cursor lives (default: beside --db, else the app's)")
    parser.add_argument("--corpus", type=Path, help="one transcript root (default: every account's projects roots)")
    parser.add_argument("--codex-root", type=Path, help="codex sessions folder (default ~/.codex/sessions; with --corpus, codex is skipped unless this is given)")
    parser.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    args = parser.parse_args(argv)
    state_dir = args.state_dir or (args.db.parent if args.db else settings.get_state_dir())
    db = args.db or db_path_for(state_dir)
    if not db.exists():
        print(f"no datastore at {db}", file=sys.stderr)
        return 2
    try:
        report = live.sweep(db, state_dir, roots=(args.corpus,) if args.corpus else None, apply=args.apply,
                            codex_root=args.codex_root, include_codex=args.corpus is None or args.codex_root is not None)
    except live.LineageLiveError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    if not args.apply:
        print("dry run: nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())

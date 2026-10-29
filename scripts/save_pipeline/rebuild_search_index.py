#!/usr/bin/env python3
"""Rebuild the deep search index: delete its cache file (``<state>/deepsearch.db``) so it rebuilds from the live transcripts.

The cache is disposable (slice DS1). Deleting it starts a new ``building`` pass: searches keep answering from the
older index until the new one has read every transcript, then switch over. Dry run by default.

    python3 scripts/save_pipeline/rebuild_search_index.py                 # dry run: what would be deleted
    python3 scripts/save_pipeline/rebuild_search_index.py --apply         # delete the cache file
    python3 scripts/save_pipeline/rebuild_search_index.py --state-dir DIR --apply   # another copy

Exit codes: 0 done, 2 could not run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="delete the cache file (default: dry run)")
    parser.add_argument("--state-dir", type=Path, help="the state directory (default: this install's)")
    args = parser.parse_args(argv)

    from src.core.deepsearch.cache import db as cache_db
    from src.core.deepsearch.cache import flip

    if args.state_dir is None:
        from src.config import settings as app_settings

        args.state_dir = app_settings.get_state_dir()
    path = cache_db.cache_path(args.state_dir)
    if not path.exists():
        print(f"no cache at {path}: nothing to delete")
        return 0
    if not args.apply:
        print(f"would delete {path} ({path.stat().st_size} bytes). pass --apply to do it.")
        return 0
    try:
        flip.reset(args.state_dir)
    except OSError as exc:
        print(f"could not delete {path}: {exc}", file=sys.stderr)
        return 2
    print(f"deleted {path}; the next scan starts a new build")
    return 0


if __name__ == "__main__":
    sys.exit(main())

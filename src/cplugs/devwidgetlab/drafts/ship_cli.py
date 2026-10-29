
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from src.cplugs.devwidgetlab.drafts import ship
from src.cplugs.devwidgetlab.errors import DraftInvalid, DraftNotFound

REPO = Path(__file__).resolve().parents[4]
EXIT_CLEAN, EXIT_PROBLEMS, EXIT_CANNOT_READ = 0, 1, 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ship a Widget Lab draft into this checkout (dry run unless --apply).")
    parser.add_argument("--draft", required=True, help="the draft folder")
    parser.add_argument("--apply", action="store_true", help="do it (default: print the plan only)")
    parser.add_argument("--keep", action="store_true", help="with --apply, leave the draft folder in place")
    parser.add_argument("--repo", default=str(REPO), help="the checkout root (default: this one)")
    parser.add_argument("--worktrees", default=None, help="the folder the throwaway worktree goes under (default ~/dev-worktrees/<repo folder>)")
    parser.add_argument("--trash", default=str(Path.home() / ".Trash"), help="where the folder goes (default ~/.Trash)")
    args = parser.parse_args(argv)
    folder = Path(args.draft).resolve()
    try:
        shipped = ship.plan(folder, Path(args.repo))
    except DraftNotFound as exc:
        print(f"cannot read the draft: {exc}", file=sys.stderr)
        return EXIT_CANNOT_READ
    print(json.dumps(shipped, indent=2))
    if shipped["problems"]:
        return EXIT_PROBLEMS
    if not args.apply:
        print("dry run: nothing was written. Add --apply to ship.", file=sys.stderr)
        return EXIT_CLEAN
    try:
        repo = Path(args.repo)
        done = ship.apply_isolated(folder, repo, Path(args.trash), Path(args.worktrees) if args.worktrees else ship.worktree_parent(repo), keep=args.keep)
    except DraftInvalid as exc:
        print(f"not shipped: {exc}", file=sys.stderr)
        return EXIT_PROBLEMS
    print(f"shipped {len(done['copy'])} files on branch {done['branch']} in {done['worktree']} (committed: {done['committed']}); draft folder: {done['trashed'] or 'kept'}", file=sys.stderr)
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Check or extend a schema rung ledger.

    venv/bin/python3 scripts/schema_ledger/cli.py check [core|huddle]
    venv/bin/python3 scripts/schema_ledger/cli.py write core --author joe

``check`` exits 0 when the ledger matches the code, 1 when it does not, 2 when it could not be read. ``write`` appends
lines for rungs the ledger lacks and refuses to touch an existing line.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.schema_ledger.ladders import LADDERS  # noqa: E402
from src.core.schema_ledger.errors import LedgerFormatError, LedgerMismatch  # noqa: E402
from src.core.schema_ledger.ledger import append_missing, check_ledger  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("check", "write"))
    parser.add_argument("ladder", nargs="?", choices=sorted(LADDERS))
    parser.add_argument("--author", default="-", help="who adds the rung (write only)")
    args = parser.parse_args(argv)
    names = [args.ladder] if args.ladder else sorted(LADDERS)
    code = 0
    for name in names:
        spec = LADDERS[name]
        try:
            if args.action == "check":
                check_ledger(spec)
                print(f"{name}: ledger matches the code")
            else:
                added = append_missing(spec, args.author)
                print(f"{name}: appended {len(added)} line(s)")
        except LedgerMismatch as exc:
            print(exc, file=sys.stderr)
            code = max(code, 1)
        except (LedgerFormatError, OSError) as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            code = 2
    return code


if __name__ == "__main__":
    sys.exit(main())

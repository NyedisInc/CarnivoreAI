
from __future__ import annotations

import json
import sys

import structlog

from src.core.diagnostics.builder import build_bundle


def main() -> int:
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
    json.dump(build_bundle(mode="offline"), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

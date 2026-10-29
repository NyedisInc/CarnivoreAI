"""Write the published JSON Schema of the sidecar from the pydantic models (``docs/reviewboard.md``, "The board format").

Usage: venv/bin/python3 -m src.cplugs.reviewboard.cli.emit_schema [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence, TextIO

from src.cplugs.reviewboard.schema import SCHEMA_ID, SCHEMA_VERSION, Sidecar

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / f"sidecar.v{SCHEMA_VERSION}.json"


def schema_text() -> str:
    body = Sidecar.model_json_schema(by_alias=True)
    head = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{SCHEMA_ID}.v{SCHEMA_VERSION}",
            "title": "review board sidecar", "description": "One board's sidecar.json; generated from src/cplugs/reviewboard/schema.py, do not edit."}
    body.pop("title", None)
    body.pop("description", None)
    return json.dumps({**head, **body}, indent=2, ensure_ascii=False) + "\n"


def main(argv: Optional[Sequence[str]] = None, out: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m src.cplugs.reviewboard.cli.emit_schema", description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare only; exit 1 when the committed file is stale")
    args = parser.parse_args(argv)
    text = schema_text()
    try:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else None
    except OSError as exc:
        out.write(f"could not read {SCHEMA_PATH}: {type(exc).__name__}\n")
        return 2
    if current == text:
        out.write(f"{SCHEMA_PATH.name} is current\n")
        return 0
    if args.check:
        out.write(f"{SCHEMA_PATH.name} is stale; run python3 -m src.cplugs.reviewboard.cli.emit_schema\n")
        return 1
    try:
        SCHEMA_PATH.write_text(text, encoding="utf-8")
    except OSError as exc:
        out.write(f"could not write {SCHEMA_PATH}: {type(exc).__name__}\n")
        return 2
    out.write(f"wrote {SCHEMA_PATH.name}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())


from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Dict

from src.core.claude_transcript_correlate import slugify_project_dir
from tests.python.inventory.world import CONV_A, CONV_A0

HARNESS_VERSION = "2.1.283"
PLAN_SLUG = "golden-plan"


def _turns(w: SimpleNamespace) -> bytes:
    plan = str(Path(w.home) / "plans" / f"{PLAN_SLUG}.md")
    records, parent = [], None
    for index, (kind, text) in enumerate((("user", "hello"), ("assistant", "hi"), ("user", "plan it"),
                                          ("assistant", f"wrote the plan to {plan}"))):
        uid = f"0000000{index}-1111-2222-3333-444444444444"
        records.append({"type": kind, "uuid": uid, "parentUuid": parent, "sessionId": CONV_A, "cwd": w.root1,
                        "version": HARNESS_VERSION, "timestamp": f"2026-10-17T20:00:0{index}Z",
                        "message": {"role": kind, "content": text}})
        parent = uid
    return b"".join(json.dumps(r).encode("utf-8") + b"\n" for r in records)


def add_extras(w: SimpleNamespace) -> Dict[str, Path]:
    folder = Path(w.home) / "projects" / slugify_project_dir(w.root1)
    paths = {
        "transcript": folder / f"{CONV_A}.jsonl",
        "tool_result": folder / CONV_A / "tool-results" / "résumé-ü.txt",
        "no_newline": folder / CONV_A / "notes.txt",
        "big": folder / f"{CONV_A0}.jsonl",
        "binary": Path(w.home) / "file-history" / CONV_A / "blob.bin",
        "plan": Path(w.home) / "plans" / f"{PLAN_SLUG}.md",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    paths["transcript"].write_bytes(_turns(w))
    paths["tool_result"].write_text("café output\n", encoding="utf-8")
    paths["no_newline"].write_bytes(b"last line without a newline")
    line = json.dumps({"type": "user", "message": {"content": "x" * 500}}).encode() + b"\n"
    paths["big"].write_bytes(line * (int(2.5 * 1024 * 1024) // len(line)))
    paths["binary"].write_bytes(bytes(range(256)) * 9000)
    paths["plan"].write_text("# the plan\n")
    return paths

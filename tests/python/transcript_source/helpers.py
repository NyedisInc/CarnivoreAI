
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

CONV = "d6bf57c2-fdbb-45a8-89f0-0857e3422fe3"
WORKDIR = "/Users/x/Library/Mobile Documents/com~apple~CloudDocs/work/proj"
FOLDER = "-Users-x-Library-Mobile-Documents-com-apple-CloudDocs-work-proj"


def transcript_lines(n_turns: int = 3) -> bytes:
    lines = []
    for i in range(n_turns):
        lines.append({"type": "user", "timestamp": f"2026-09-0{i + 1}T10:00:00Z",
                      "message": {"role": "user", "content": f"prompt number {i}"}})
        lines.append({"type": "assistant", "message": {"model": "m", "content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/a/b.py"}}]}})
    lines.append({"type": "system", "subtype": "compact_boundary"})
    return ("\n".join(json.dumps(x) for x in lines) + "\n").encode()


def make_corpus(tmp_path: Path, conv: str = CONV, body: Optional[bytes] = None,
                subagents: int = 2) -> Path:
    corpus = tmp_path / "corpus"
    folder = corpus / FOLDER
    folder.mkdir(parents=True)
    (folder / f"{conv}.jsonl").write_bytes(body if body is not None else transcript_lines())
    if subagents:
        sub = folder / conv / "subagents"
        sub.mkdir(parents=True)
        for i in range(subagents):
            (sub / f"agent-{i}.jsonl").write_bytes(b'{"type":"user"}\n' * (i + 1))
    return corpus


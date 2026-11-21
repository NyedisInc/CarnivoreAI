
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def claude_record(text: str, at: float, *, usage: Optional[Dict[str, int]] = None, msg_id: str = "msg_1") -> Dict[str, Any]:
    message: Dict[str, Any] = {"id": msg_id, "role": "assistant", "model": "claude-sonnet-4-5", "content": [{"type": "text", "text": text}]}
    if usage is not None:
        message["usage"] = usage
    return {"type": "assistant", "timestamp": iso(at), "message": message}


def codex_record(text: str, at: float) -> Dict[str, Any]:
    return {"type": "response_item", "timestamp": iso(at), "payload": {"role": "assistant", "content": [{"type": "output_text", "text": text}]}}


def write_claude(root: Path, conversation: str, records: List[Dict[str, Any]]) -> Path:
    path = root / "projects" / "-slot" / f"{conversation}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def write_codex(root: Path, conversation: str, records: List[Dict[str, Any]]) -> Path:
    path = root / "sessions" / "2026" / "11" / "16" / f"rollout-2026-11-16T10-00-00-{conversation}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def main(argv: List[str]) -> int:
    record = Path(argv[1])
    task_file = Path(".carnivore-job") / "task.md"
    task = task_file.read_text(encoding="utf-8") if task_file.is_file() else None
    out: Dict[str, Any] = {
        "argv": argv[2:], "env_names": sorted(os.environ), "cwd": os.getcwd(), "task_read": task,
        "task_mode": oct(task_file.stat().st_mode & 0o777) if task is not None else None,
        "task_in_argv": bool(task) and any(task.strip() in a for a in argv),
    }
    if task is not None:
        Path("worker-out.txt").write_text("worker did: " + task.strip().splitlines()[0] + "\n", encoding="utf-8")
    if "--push" in argv:
        subprocess.run(["git", "remote", "add", "origin", "https://example.invalid/x.git"], capture_output=True, check=False)
        pushed = subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True, text=True, check=False)
        out["push"] = {"code": pushed.returncode, "stderr": pushed.stderr}
    record.write_text(json.dumps(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

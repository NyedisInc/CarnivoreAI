
from __future__ import annotations

import os
import secrets
from pathlib import Path
from types import SimpleNamespace

from tests.python.inventory.world import CONV_A, CONV_A0


def plant_canaries(w: SimpleNamespace) -> str:
    canary = "crate-canary-" + secrets.token_hex(12)
    for path in (Path(w.codex) / "auth.json", Path(w.codex) / "state_5.sqlite", Path(w.home) / ".credentials.json",
                 Path(w.home) / "session-env" / CONV_A / "env.sh"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'{{"secret": "{canary}"}}\n')
    return canary


def plant_symlink(w: SimpleNamespace) -> Path:
    link = Path(w.codex) / "sessions" / "2026" / "10" / "10" / f"rollout-2026-10-10T00-00-00-{CONV_A}.jsonl"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(Path(w.codex) / "auth.json", link)
    return link


def plant_hardlink(w: SimpleNamespace) -> Path:
    link = Path(w.codex) / "sessions" / "2026" / "10" / "11" / f"rollout-2026-10-11T00-00-00-{CONV_A0}.jsonl"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.link(Path(w.codex) / "auth.json", link)
    return link

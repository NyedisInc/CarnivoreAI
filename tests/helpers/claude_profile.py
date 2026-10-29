
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def write_claude_profile(
    profile_dir: str,
    *,
    setup_complete: bool = True,
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    document: Dict[str, Any] = {"oauthAccount": {"emailAddress": "someone@example.invalid"}}
    if setup_complete:
        document["hasCompletedOnboarding"] = True
    document.update(extra or {})
    path = Path(profile_dir) / ".claude.json"
    path.write_text(json.dumps(document, indent=2))
    os.chmod(path, 0o600)
    return path


def refuse_writes_outside(tmp_path: Path, monkeypatch) -> List[str]:
    from src.core import config_writer

    real_open = config_writer._open_with_mode
    root = str(tmp_path.resolve())
    refused: List[str] = []

    def guarded(path, mode, *, exclusive):
        if not str(Path(path).resolve()).startswith(root):
            refused.append(str(path))
            raise AssertionError(f"refused a write outside the temp home: {path}")
        return real_open(path, mode, exclusive=exclusive)

    monkeypatch.setattr(config_writer, "_open_with_mode", guarded)
    return refused


def temp_home(tmp_path: Path, monkeypatch, *, default: Dict[str, Any]) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLOUDE_SHARED_MCP_PATH", str(tmp_path / ".claude" / "carnivore-mcp.json"))
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    (tmp_path / ".claude" / "sessions").mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    path = tmp_path / ".claude.json"
    path.write_text(json.dumps(default))
    os.chmod(path, 0o600)
    return tmp_path

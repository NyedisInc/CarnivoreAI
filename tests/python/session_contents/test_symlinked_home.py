
from __future__ import annotations

import json
from pathlib import Path

from src.core.session_contents import claude
from src.core.session_contents import constants as C


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_symlinked_home_claude_does_not_duplicate_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CLAUDE_MANAGED_DIRS", ())
    shared, home, cfg = tmp_path / "shared", tmp_path / "home", tmp_path / "cfg"
    monkeypatch.setenv("HOME", str(home))
    _write(shared / "commands" / "deploy.md", "---\ndescription: ship\n---\n")
    _write(shared / "skills" / "alpha" / "SKILL.md", "---\nname: alpha\ndescription: a\n---\n")
    _write(shared / "agents" / "helper.md", "---\ndescription: h\n---\n")
    _write(shared / "settings.json", json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/bin/x"}]}]}}))
    cfg.mkdir()
    for name in ("commands", "skills", "agents", "settings.json"):
        (cfg / name).symlink_to(shared / name)
    (home / "work" / "proj").mkdir(parents=True)
    (home / ".claude").symlink_to(shared)

    sections = {s["kind"]: s["items"] for s in claude.gather(str(cfg), str(home / "work" / "proj"))}

    for kind, name in ((C.KIND_COMMANDS, "deploy"), (C.KIND_SKILLS, "alpha"), (C.KIND_AGENTS, "helper")):
        found = [i for i in sections[kind] if i["name"] == name]
        assert [i["scope"] for i in found] == [C.SCOPE_GLOBAL], kind
    assert len(sections[C.KIND_HOOKS]) == 1
    assert len(sections[C.KIND_SETTINGS]) == 1

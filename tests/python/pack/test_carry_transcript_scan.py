
from __future__ import annotations

import json
from pathlib import Path

from src.core.pack.carry import transcript_scan


def _use(name: str, **inp) -> str:
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}})


def test_the_transcript_since_the_last_compaction_is_classified(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root, scratch, old = home / "proj", home / "~/work" / "bubblepop", home / "oldscratch"
    other_wt, secrets = home / "wt" / "other-feature", home / ".carnivore" / "state"
    for d in (root, scratch, old, other_wt, secrets, home / "other"):
        d.mkdir(parents=True)
    (scratch / "a.txt").write_text("x" * 10)
    for f in (old / "x", other_wt / "f", secrets / "cfg", root / "inside.py"):
        f.write_text("y")
    lines = [_use("Read", file_path=str(old / "x")), json.dumps({"type": "system", "subtype": "compact_boundary"}),
             _use("Write", file_path=str(scratch / "a.txt")), _use("Read", file_path=str(other_wt / "f")), _use("Read", file_path=str(secrets / "cfg")),
             _use("Read", file_path=str(root / "inside.py")),
             _use("Bash", command="cd proj && python3 -m http.server 5041 --token=abcdefghijklmnopqrstuvwxyz0123456789", run_in_background=True),
             "not json at all"]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(lines) + "\n")
    found = transcript_scan.scan_transcript(str(path), root=str(root), other_projects={"other": str(home / "other")},
                                            worktrees_of=lambda r: [str(other_wt)], home=str(home), is_listening=lambda port: port == 5041)
    by_kind = {f["kind"]: f for f in found.folders}
    assert [f["path"] for f in found.folders if f["kind"] == "outside"] == [str(scratch.resolve())], found.folders
    assert by_kind["outside"]["tick"] is True and by_kind["outside"]["size"] == 10
    assert by_kind["other_project"]["project"] == "other" and by_kind["other_project"]["path"] == str(other_wt.resolve())
    assert found.dropped == [str(secrets.resolve())]
    assert len(found.servers) == 1 and found.servers[0]["port"] == 5041 and "abcdefghijklmnopqrstuvwxyz" not in found.servers[0]["command"]
    view = found.view(False)
    assert view["outside"][0]["carryable"] is False and "dropped" not in view

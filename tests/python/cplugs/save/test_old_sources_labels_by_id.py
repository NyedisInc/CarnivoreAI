
from __future__ import annotations

import json
from pathlib import Path

from src.cplugs.save.vault.old_sources import labels

CONV = "aaaaaaaa-0000-0000-0000-00000000000a"
ALPHA = "358719f7-8887-48cc-848f-68ac983dc2e4"
ENC = "-Users-x-Alpha"


def test_a_sub_agent_file_and_a_trash_entry_with_other_bytes_are_labeled(tmp_path: Path) -> None:
    plan = {"conversations": [{"conversation_id": CONV, "verdict": "delete", "reasons": ["empty"], "files": [
        {"path": f"/h/.claude/projects/{ENC}/{CONV}.jsonl"},
        {"path": "/h/.claude/projects/-Users-x--claude/agent-a4c54b1.jsonl"},
        {"path": f"/h/.claude/projects/{ENC}/{CONV}/subagents/agent-bee1234.jsonl"}]}]}
    plan_file = tmp_path / "plan-applied.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    manifest = tmp_path / "trash.sha256"
    manifest.write_text(f"{'0' * 64}  ./transcripts/{ENC}/{ALPHA}.jsonl\n{'1' * 64}  ./time-machine/Alpha/{ALPHA}/current/meta.json\n", encoding="utf-8")
    book = labels.LabelBook.load(plan_applied=plan_file, trash_manifests=[manifest])
    assert book.for_conversation("agent-a4c54b1") == ("junk-20260930:empty",)
    assert book.for_conversation("agent-bee1234") == ("junk-20260930:empty",)
    assert book.for_conversation(CONV) == ("junk-20260930:empty",)
    assert book.for_conversation(ALPHA, ENC) == ("trash-20261016",)

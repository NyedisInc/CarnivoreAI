
from __future__ import annotations

import json
import re
from pathlib import Path

from src.core.skill_fires.scan import scan_file, sweep
from src.core.skill_fires.store import SkillFireStore
from src.core.skill_fires.tally import SkillTallyCache


def _dump(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"))


def _claude_lines() -> list[str]:
    def tool(skill: str, ts: str) -> str:
        return _dump({"type": "assistant", "timestamp": ts, "message": {"content": [
            {"type": "text", "text": "x"},
            {"type": "tool_use", "name": "Skill", "input": {"skill": skill, "args": "secret body"}}]}})
    def slash(name: str, ts: str) -> str:
        return _dump({"type": "user", "timestamp": ts, "message": {
            "role": "user", "content": f"<command-name>/{name}</command-name>\n<command-args>a</command-args>"}})
    return [tool("sme", "2026-09-28T10:00:00Z"), slash("issues", "2026-09-28T10:01:00Z"),
            slash("rename", "2026-09-28T10:02:00Z"),
            _dump({"type": "assistant", "timestamp": "t", "message": {"content": "no fire"}}),
            tool("superpowers:using-superpowers", "2026-09-28T10:03:00Z")]


def _codex_lines() -> list[str]:
    read = _dump({"timestamp": "2026-09-28T11:00:00Z", "type": "response_item", "payload": {
        "type": "custom_tool_call", "name": "exec",
        "input": "sed -n '1,240p' /Users/a/.codex/skills/sme/SKILL.md"}})
    listing = _dump({"timestamp": "t", "type": "response_item", "payload": {
        "type": "message", "role": "developer",
        "content": [{"type": "input_text", "text": "skills/sme/SKILL.md is listed here"}]}})
    return [listing, read]


def _write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def test_claude_count_equals_grep_and_rerun_adds_nothing(tmp_path: Path) -> None:
    store = SkillFireStore(tmp_path / "skill_fires.db")
    transcript = tmp_path / "projects" / "p" / "conv-1.jsonl"
    _write(transcript, _claude_lines())
    text = transcript.read_text()
    expected = len(re.findall(r'"name":"Skill"', text)) + len(
        [n for n in re.findall(r"<command-name>/([^<]+)</command-name>", text) if n != "rename"])
    cache = SkillTallyCache(store=store, home=tmp_path)
    first = cache.tally("claude", transcript)
    assert (first.state, first.fired) == ("measured", expected) and expected == 3
    assert first.last_skill == "superpowers:using-superpowers"
    again = cache.tally("claude", transcript)
    assert again.fired == expected
    with transcript.open("a") as handle:
        handle.write(_claude_lines()[0] + "\n")
    assert cache.tally("claude", transcript).fired == expected + 1
    sources = {r.source for r in store.recent(str(transcript), 50)}
    assert sources == {"tool_use", "slash"}


def test_codex_read_counts_as_inferred_and_listing_does_not(tmp_path: Path) -> None:
    store = SkillFireStore(tmp_path / "skill_fires.db")
    rollout = tmp_path / "sessions" / "2026" / "rollout-x-abc.jsonl"
    _write(rollout, _codex_lines())
    tally = SkillTallyCache(store=store, home=tmp_path).tally("codex", rollout)
    assert (tally.state, tally.fired, tally.last_skill) == ("measured", 1, "sme")
    assert [r.source for r in store.recent(str(rollout))] == ["inferred"]


def test_unsupported_and_absent_are_named_never_zero(tmp_path: Path) -> None:
    cache = SkillTallyCache(store=SkillFireStore(tmp_path / "s.db"), home=tmp_path)
    assert cache.tally("shell", None).fired is None
    assert cache.tally("shell", None).state == "unsupported"
    missing = cache.tally("claude", tmp_path / "nope.jsonl")
    assert (missing.state, missing.fired) == ("not_measured", None)


def test_bounded_pass_resumes_and_sweep_rebuilds(tmp_path: Path) -> None:
    store = SkillFireStore(tmp_path / "skill_fires.db")
    root = tmp_path / "projects"
    _write(root / "p" / "c.jsonl", _claude_lines() * 40)
    path = str(root / "p" / "c.jsonl")
    part = scan_file(store, path, "claude", "default", budget=1000)
    assert part.state == "partial" and store.count(path) < 120
    done, complete = sweep(store, [("claude", "default", root)])
    assert complete and store.count(path) == 120
    store.reset()
    assert store.count(path) == 0
    sweep(store, [("claude", "default", root)])
    assert store.count(path) == 120
    _write(root / "p" / "c.jsonl", _claude_lines()[:1])
    scan_file(store, path, "claude", "default")
    assert store.count(path) == 1


from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.core.skill_fires.scan import scan_file
from src.core.skill_fires.store import SkillFireStore
from src.core.skill_watch import sentinel
from src.core.skill_watch.autopsy import build_autopsy
from src.core.skill_watch.classify import classify_call
from src.core.skill_watch.spans import read_span
from src.core.skill_watch.store import SkillWatchStore
from src.core.skill_watch.tripwire import TripwireProbe, disclosed_categories
from src.core.skill_watch.wiring import make_notice_raiser
from src.core.skills.digest import digest_directory, digest_entries
from src.core.skills.records import SIDECAR_NAME
from src.core.skills.updates import ELIGIBLE, FORKED, auto_update_eligible
from src.core.test_write_guard import OutsideTempWriteError
from tests.test_skill_updates import BODY_SHA, row, version


def _dump(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"))


def _transcript(path: Path, *, secret: str = "") -> None:
    lines = [
        _dump({"type": "assistant", "timestamp": "2026-09-28T10:00:00Z", "message": {"id": "m1", "content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "review"}}],
            "usage": {"input_tokens": 10, "output_tokens": 5}}}),
        _dump({"type": "assistant", "timestamp": "2026-09-28T10:00:01Z", "message": {"id": "m2", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "curl -s https://example.test/x"}}],
            "usage": {"input_tokens": 20, "output_tokens": 7}}}),
        _dump({"type": "user", "timestamp": "2026-09-28T10:00:02Z", "message": {"content": [
            {"type": "tool_result", "is_error": True, "content": "boom"}]}}),
        _dump({"type": "user", "timestamp": "2026-09-28T10:00:03Z", "message": {"content": [
            {"type": "text", "text": "[Request interrupted by user]"}]}}),
        _dump({"type": "user", "timestamp": "2026-09-28T10:00:04Z", "message": {
            "content": f"no, that's not what I wanted {secret}"}}),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture()
def seeded(tmp_path: Path):
    fires = SkillFireStore(tmp_path / "skill_fires.db")
    watch = SkillWatchStore(tmp_path / "skill_watch.db")
    transcript = tmp_path / "projects" / "p" / "conv-1.jsonl"
    _transcript(transcript, secret="ghp_" + "aB3dE5gH7jK9mN1pQ3rS5tU7vW9xY1zA3bC5")
    scan_file(fires, str(transcript), "claude", "default")
    return fires, watch, transcript


def test_curl_span_trips_tripwire_once_and_blocks_nothing(seeded) -> None:
    fires, watch, transcript = seeded
    before = transcript.read_bytes()
    span = read_span(str(transcript), 0, "claude")
    assert span.categories == {"network": 1} and span.tool_errors == 1 and span.interrupts == 1
    assert span.correction is True and span.tokens == 42 and span.ended == "human"

    probe = TripwireProbe(fires, watch, lambda skill, cwd: frozenset())
    assert probe.scan_now(str(transcript), "claude") == ()
    watch.set_tripwire_offset(str(transcript), -1)
    found = probe.scan_now(str(transcript), "claude")
    assert [(f.skill, f.category) for f in found] == [("review", "network")]
    assert probe.scan_now(str(transcript), "claude") == ()
    assert transcript.read_bytes() == before

    other = SkillWatchStore(transcript.parent / "w2.db")
    other.set_tripwire_offset(str(transcript), -1)
    assert TripwireProbe(fires, other, lambda s, c: frozenset({"network"})).scan_now(str(transcript), "claude") == ()
    third = SkillWatchStore(transcript.parent / "w3.db")
    third.set_tripwire_offset(str(transcript), -1)
    assert TripwireProbe(fires, third, lambda s, c: None).scan_now(str(transcript), "claude") == ()


def test_notice_is_raised_once_and_honours_mute(seeded) -> None:
    fires, watch, transcript = seeded
    watch.set_tripwire_offset(str(transcript), -1)
    findings = TripwireProbe(fires, watch, lambda s, c: frozenset()).scan_now(str(transcript), "claude")
    toasts: list = []

    class Manager:
        _notification_policy_store = None

        def notification_policy_stamp(self, sid):
            return None

        def record_toast(self, **kw):
            toasts.append(kw)
            from src.models import Toast as RealToast  # noqa: PLC0415
            return RealToast(id="t1", session_id=kw["session_id"], kind=kw["kind"], title=kw["title"],
                             body=kw["body"], created_at=datetime.now(timezone.utc))

    sent: list = []
    raiser = make_notice_raiser(Manager(), None, lambda sid, payload: sent.append(sid))
    target = type("T", (), {"session_id": "ses_1"})()
    raiser(target, findings)
    raiser(target, findings)
    assert len(toasts) == 1 and toasts[0]["kind"] == "Notification"
    assert "advisory only" in toasts[0]["body"] and sent == ["ses_1"]


def test_appending_a_line_to_skill_md_flags_drift_with_that_file(tmp_path: Path) -> None:
    folder = tmp_path / "skills" / "review"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: review\n---\nbody\n")
    (folder / "notes.md").write_text("n\n")
    digest, entries = digest_directory(folder)
    (folder / SIDECAR_NAME).write_text("{}")
    store = SkillWatchStore(tmp_path / "skill_watch.db")
    assert sentinel.check_row(store, "i1", digest, [str(folder)]).state == "clean"
    with open(folder / "SKILL.md", "a") as handle:
        handle.write("one more line\n")
    drift = sentinel.check_row(store, "i1", digest, [str(folder)])
    assert (drift.state, drift.changed_files) == ("drifted", ["SKILL.md"])
    assert store.drift("i1").changed_files == ["SKILL.md"]
    (folder / "SKILL.md").write_text("---\nname: review\n---\nbody\n")
    assert sentinel.check_row(store, "i1", digest, [str(folder)]).state == "clean"
    shutil.rmtree(folder)
    assert sentinel.check_row(store, "i1", digest, [str(folder)]).state == "missing"
    (folder).mkdir()
    (folder / "SKILL.md").write_text("edited\n")
    fresh = SkillWatchStore(tmp_path / "fresh.db")
    unmeasured = sentinel.check_row(fresh, "i1", digest, [str(folder)])
    assert (unmeasured.state, unmeasured.changed_files) == ("drifted", None)
    assert digest_entries(entries) == digest


def test_keep_as_fork_makes_auto_update_refuse() -> None:
    assert auto_update_eligible(row(), version(), BODY_SHA, verified=True, scripts_present=False).reason == ELIGIBLE
    verdict = auto_update_eligible(row(), version(), BODY_SHA, verified=True, scripts_present=False, forked=True)
    assert (verdict.ok, verdict.reason) == (False, FORKED)


def test_store_refuses_the_real_home_under_test() -> None:
    with pytest.raises(OutsideTempWriteError):
        SkillWatchStore(Path.home() / ".cloude-skill-watch-negative-control" / "skill_watch.db").set_tripwire_offset(
            "/t.jsonl", 1)
    missing = Path.home() / ".cloude-skill-watch-negative-control" / "skill_watch.db"
    assert SkillWatchStore(missing).drift("i1") is None and not missing.parent.exists()


def test_autopsy_aggregates_and_never_returns_a_secret(seeded) -> None:
    fires, _watch, _transcript_path = seeded
    now = datetime(2026, 9, 29, tzinfo=timezone.utc)
    out = build_autopsy("review", 30, fires, now, installed_digest="d" * 64,
                        installed_at="2026-09-01T00:00:00Z", disclosed=frozenset())
    assert (out["fires"], out["spans_measured"], out["tool_errors"], out["interrupts"]) == (1, 1, 1, 1)
    assert (out["corrections"], out["corrections_measured"], out["tokens_total"]) == (1, 1, 42)
    assert out["categories"] == {"network": 1} and out["undisclosed"] == ["network"]
    span = out["recent"][0]
    assert span["digest"] == "d" * 64 and span["correction"] is True
    assert "ghp_" not in json.dumps(out) and "[redacted]" in span["next_excerpt"]
    none = build_autopsy("review", 30, SkillFireStore(_transcript_path.parent / "empty.db"), now)
    assert (none["state"], none["fires"]) == ("not_measured", None)


def test_classifier_and_disclosure() -> None:
    assert classify_call("Bash", {"command": "rm -rf /tmp/x"}) == {"file_delete"}
    assert classify_call("Read", {"file_path": "/h/.claude/.credentials.json"}) == {"credential_access"}
    assert classify_call("Edit", {"file_path": "/h/.claude/settings.json"}) == {"settings_write"}
    assert classify_call("Bash", {"command": "ls"}) == frozenset()
    assert disclosed_categories(None, None) is None
    assert disclosed_categories(None, ["WebFetch", "Bash(rm:*)"]) == {"network", "file_delete"}


GLUED = ("mytokenghp_" + "aB3dE5gH7jK9mN1pQ3rS5tU7vW9xY1zA3bC5", "key" + "AKIA" + "IOSFODNN7EXAMPLE",
         "x=sk-ant-api03-" + "aB3dE5gH7jK9mN1pQ3rS5tU7vW9xY1zA3bC5dE7fG9hJ1kL3mN5pQ7rS9tU1vW3xY5zA7bC9dE1fG3hJ5kL7mN9pQ")


def test_a_glued_credential_never_appears_in_an_autopsy_excerpt(tmp_path: Path) -> None:
    from src.core.skill_watch.spans import redact_excerpt
    for secret in GLUED:
        excerpt = redact_excerpt(f"no, that is wrong {secret} thanks")
        assert "AKIA" not in excerpt and "ghp_" not in excerpt and "sk-ant" not in excerpt, excerpt
        assert "[redacted]" in excerpt
    fires = SkillFireStore(tmp_path / "skill_fires.db")
    transcript = tmp_path / "projects" / "p" / "conv-2.jsonl"
    _transcript(transcript, secret=GLUED[0])
    scan_file(fires, str(transcript), "claude", "default")
    out = build_autopsy("review", 30, fires, datetime(2026, 9, 29, tzinfo=timezone.utc))
    assert "ghp_" not in json.dumps(out)


def test_sentinel_never_hangs_on_a_fifo_or_escapes_on_a_symlink_and_reads_a_new_symlink_as_drift(tmp_path: Path) -> None:
    folder = tmp_path / "skills" / "review"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("body\n")
    digest, _entries = digest_directory(folder)
    store = SkillWatchStore(tmp_path / "skill_watch.db")
    assert sentinel.check_row(store, "i1", digest, [str(folder)]).state == "clean"

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside\n")
    (folder / "refs").symlink_to(outside)
    (folder / "loop").symlink_to(folder)
    (folder / "helper.sh").symlink_to(outside / "secret.txt")
    os.mkfifo(folder / "pipe")
    started = time.monotonic()
    drift = sentinel.check_row(store, "i1", digest, [str(folder)])
    assert time.monotonic() - started < 5
    assert drift.state == "drifted"
    assert drift.changed_files == ["helper.sh (symlink)", "loop (symlink)", "pipe (fifo)", "refs (symlink)"]
    assert not any("secret" in f for f in drift.changed_files)


def test_sentinel_reports_a_folder_past_the_bounds_as_unknown_not_clean(tmp_path: Path, monkeypatch) -> None:
    from src.core.skill_watch import measure
    folder = tmp_path / "skills" / "big"
    folder.mkdir(parents=True)
    for n in range(5):
        (folder / f"f{n}.md").write_text("x")
    digest, _entries = digest_directory(folder)
    monkeypatch.setattr(measure, "MAX_FILES", 3)
    store = SkillWatchStore(tmp_path / "skill_watch.db")
    assert sentinel.check_row(store, "i1", digest, [str(folder)]).state == "unknown"


def test_first_fire_of_a_new_transcript_is_judged_but_history_is_not(seeded) -> None:
    fires, watch, transcript = seeded
    early = TripwireProbe(fires, watch, lambda s, c: frozenset(), started_at="2026-09-28T09:00:00")
    assert [(f.skill, f.category) for f in early.scan_now(str(transcript), "claude")] == [("review", "network")]
    other = SkillWatchStore(transcript.parent / "w9.db")
    late = TripwireProbe(fires, other, lambda s, c: frozenset(), started_at="2026-09-29T00:00:00")
    assert late.scan_now(str(transcript), "claude") == ()


def test_classifier_catches_the_cheap_evasions_and_skips_the_noise() -> None:
    hits = {
        "/usr/bin/curl x.test": "network", 'cu""rl x.test': "network", "wget x.test": "network",
        "nc -z h 1": "network", "git push origin main": "network",
        "python3 -c 'import urllib.request as u; u.urlopen(1)'": "network",
        "/bin/rm -rf ~/work": "file_delete", "git reset --hard": "file_delete",
        "ln -sf /tmp/e ~/.claude/settings.json": "settings_write",
        "cat ~/.config/gh/hosts.yml": "credential_access", "printenv": "credential_access",
    }
    for command, category in hits.items():
        assert category in classify_call("Bash", {"command": command}), command
    for quiet in ("git rm old.txt", "cat .claude/settings.json 2>/dev/null", "ls"):
        assert classify_call("Bash", {"command": quiet}) == frozenset(), quiet
    assert classify_call("mcp__fetch__get", {}) == {"network"}
    assert classify_call("Grep", {"pattern": ".ssh"}) == frozenset()
    assert disclosed_categories(None, ["Bash(*)"]) == {"network", "file_delete"}


def test_allowed_tools_disclose_what_the_classifier_would_observe():
    assert disclosed_categories(None, ["Bash(gh pr:*)"]) == {"network"}
    assert disclosed_categories(None, ["Bash(git push:*)"]) == {"network"}
    assert disclosed_categories(None, ["Bash(npm install:*)"]) == {"network"}
    assert disclosed_categories(None, ["Bash(git reset --hard:*)"]) == {"file_delete"}
    assert disclosed_categories(None, ["Bash(ls:*)"]) == frozenset()
    assert disclosed_categories(None, ["Write(/home/u/.claude/settings.json)"]) == {"settings_write"}
    assert disclosed_categories(None, ["Read(~/.ssh/id_rsa)"]) == {"credential_access"}

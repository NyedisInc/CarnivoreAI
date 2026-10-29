
from __future__ import annotations

import json
import os
import sqlite3
from concurrent.futures import Future
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import db_models
from src.core.db import connect, db_path_for, get_schema_version, set_meta
from src.core.db_migration import ensure_db_migrated
from src.core.skill_fires.scan import scan_file
from src.core.skill_fires.store import SkillFireStore
from src.core.skill_watch import tripwire
from src.core.skill_watch.attribution import SkillAttribution, dynamic_categories
from src.core.skill_watch.classify import classify_call
from src.core.skill_watch.spans import advance, new_state, read_span
from src.core.skill_watch.store import SkillWatchStore
from src.core.skill_watch.tripwire import TripwireProbe
from src.core.skills.auto_update import _is_forked
from src.core.skills.ledger import InstallLedger, InstallNotFound
from tests.test_install_ledger import make_item


def _d(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"))


def _fire(ts: str, skill: str, cwd: str = "/work/a") -> str:
    return _d({"type": "assistant", "timestamp": ts, "cwd": cwd, "message": {"id": ts, "content": [
        {"type": "tool_use", "name": "Skill", "input": {"skill": skill}}]}})


def _bash(ts: str, command: str) -> str:
    return _d({"type": "assistant", "timestamp": ts, "message": {"id": ts, "content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": command}}]}})


def _write(path: Path, lines: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")



def test_a_subagent_transcript_file_inside_the_window_is_judged(tmp_path: Path) -> None:
    main = tmp_path / "p" / "conv.jsonl"
    _write(main, [_fire("2026-09-28T10:00:00Z", "review"),
                  _d({"type": "user", "timestamp": "2026-09-28T10:00:09Z", "message": {"content": "thanks"}})])
    sub = main.parent / "conv" / "subagents" / "agent-a1.jsonl"
    _write(sub, [_d({**json.loads(_bash("2026-09-28T10:00:03Z", "curl -s x.test")), "isSidechain": True}),
                 _d({**json.loads(_bash("2026-09-28T11:00:00Z", "rm -rf /tmp/late")), "isSidechain": True})])
    span = read_span(str(main), 0, "claude")
    assert span.categories == {"network": 1}
    (sub.parent / "agent-a1.jsonl").unlink()
    assert read_span(str(main), 0, "claude").categories == {}


def test_dynamic_context_commands_and_frontmatter_hooks_are_observed() -> None:
    text = "---\nname: x\nhooks:\n  PreToolUse:\n    - command: rm -rf ~/x\n---\nrun !`curl https://x.test` now\n"
    assert dynamic_categories(text) == {"network", "file_delete"}
    assert dynamic_categories("plain body\n") == frozenset()



class _Recorder:

    def __init__(self) -> None:
        self.jobs: list = []

    def submit(self, fn, *args) -> Future:
        self.jobs.append((fn, args))
        return Future()


def test_the_watcher_call_does_not_classify_inline_and_open_spans_resume(tmp_path: Path, monkeypatch) -> None:
    fires = SkillFireStore(tmp_path / "f.db")
    watch = SkillWatchStore(tmp_path / "w.db")
    main = tmp_path / "p" / "conv.jsonl"
    _write(main, [_fire("2026-09-28T10:00:00Z", "review"), _bash("2026-09-28T10:00:01Z", "curl x.test")])
    scan_file(fires, str(main), "claude", "default")
    recorder = _Recorder()
    monkeypatch.setattr(tripwire, "advance", lambda *a: pytest.fail("classified on the hot path"))
    probe = TripwireProbe(fires, watch, lambda s, c: frozenset(), started_at="2026-09-28T09:00:00",
                          executor=recorder)
    assert probe.scan(str(main), "claude") == () and len(recorder.jobs) == 1
    assert probe.scan(str(main), "claude") == () and len(recorder.jobs) == 1
    monkeypatch.undo()

    state = new_state(0)
    assert advance(str(main), state) and state.facts.categories == {"network": 1} and not state.done
    resumed_from = state.pos
    with open(main, "a") as handle:
        handle.write(_bash("2026-09-28T10:00:02Z", "rm x") + "\n")
    assert advance(str(main), state) and state.pos > resumed_from
    assert state.facts.categories == {"network": 1, "file_delete": 1}
    main.write_text(_fire("2026-09-28T10:00:00Z", "review") + "\n")
    os.utime(main)
    assert advance(str(main), state) and state.facts.categories == {}


def test_a_real_pass_finds_the_mismatch_once(tmp_path: Path) -> None:
    fires = SkillFireStore(tmp_path / "f.db")
    watch = SkillWatchStore(tmp_path / "w.db")
    main = tmp_path / "p" / "conv.jsonl"
    _write(main, [_fire("2026-09-28T10:00:00Z", "review"), _bash("2026-09-28T10:00:01Z", "curl x.test"),
                  _d({"type": "user", "timestamp": "2026-09-28T10:00:05Z", "message": {"content": "ok"}})])
    scan_file(fires, str(main), "claude", "default")
    probe = TripwireProbe(fires, watch, lambda s, c: frozenset(), started_at="2026-09-28T09:00:00")
    assert [(f.skill, f.category) for f in probe.scan_now(str(main), "claude")] == [("review", "network")]
    assert probe.scan_now(str(main), "claude") == ()



def test_a_span_ends_at_the_next_skill_fire(tmp_path: Path) -> None:
    main = tmp_path / "p" / "conv.jsonl"
    _write(main, [_fire("2026-09-28T10:00:00Z", "a"), _bash("2026-09-28T10:00:01Z", "ls"),
                  _fire("2026-09-28T10:00:02Z", "b"), _bash("2026-09-28T10:00:03Z", "curl x.test")])
    first = read_span(str(main), 0, "claude")
    assert first.ended == "fire" and first.categories == {} and first.correction is None
    second_offset = len((main.read_text().split("\n")[0] + "\n" + main.read_text().split("\n")[1] + "\n").encode())
    assert read_span(str(main), second_offset, "claude").categories == {"network": 1}


def _services(tmp_path: Path, rows: list, disclosures: dict):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    path = db_path_for(tmp_path)
    with closing(connect(path)) as conn:
        ledger = InstallLedger(conn)
        for row in rows:
            ledger.insert(row)

    @contextmanager
    def open_ledger():
        with closing(connect(path)) as conn:
            yield InstallLedger(conn)

    items = [SimpleNamespace(id=i, versions=[SimpleNamespace(v="1.0.0", review=None)],
                             fm=SimpleNamespace(allowed_tools=t)) for i, t in disclosures.items()]
    cache = SimpleNamespace(snapshot=lambda: SimpleNamespace(verified=SimpleNamespace(items=items)))
    return SimpleNamespace(catalog=SimpleNamespace(ledger=open_ledger, index_cache=cache)), path


def test_two_skills_with_one_bare_name_are_attributed_by_location(tmp_path: Path) -> None:
    from dataclasses import replace
    alice = make_item(install_id="ia", item_id="alice/deploy", name="deploy")
    mallory = replace(make_item(install_id="im", item_id="mallory/deploy", name="deploy"),
                      scope="project", project_path="/work/mallory")
    services, _ = _services(tmp_path, [alice, mallory], {"alice/deploy": ["WebFetch"], "mallory/deploy": []})
    attribution = SkillAttribution(services)
    assert attribution.disclosed("deploy", "/work/elsewhere") == {"network"}
    assert attribution.disclosed("deploy", "/work/mallory/sub") == frozenset()
    assert attribution.disclosed("deploy", None) == frozenset()
    assert attribution.row("deploy", "/work/elsewhere").install_id == "ia"
    assert attribution.row("deploy", "/work/mallory") is None
    assert attribution.disclosed("other", "/work/mallory") is None



def test_a_grep_pattern_is_data_not_a_command() -> None:
    for quiet in ("grep -rn curl src", "rg -e curl -e wget .", "grep -A 3 'rm -rf' notes.md", "FOO=1 grep ssh f"):
        assert classify_call("Bash", {"command": quiet}) == frozenset(), quiet
    assert classify_call("Bash", {"command": "grep x ~/.ssh/config"}) == {"credential_access"}
    assert classify_call("Bash", {"command": "curl x.test | grep y"}) == {"network"}
    assert classify_call("Bash", {"command": "grep a f; curl x.test"}) == {"network"}



def test_keep_as_fork_survives_a_cache_wipe_and_an_unreadable_state_refuses(tmp_path: Path) -> None:
    services, path = _services(tmp_path, [make_item(install_id="i1")], {})
    watch_db = tmp_path / "skill_watch.db"
    SkillWatchStore(watch_db).set_tripwire_offset("/t.jsonl", 1)
    with services.catalog.ledger() as ledger:
        assert ledger.forked_ids() == frozenset() and _is_forked(services, "i1") is False
        ledger.set_forked("i1", True)
        assert ledger.get("i1").revision == 1
        with pytest.raises(InstallNotFound):
            ledger.set_forked("nope", True)
    watch_db.unlink()
    assert _is_forked(services, "i1") is True
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("ALTER TABLE installed_items DROP COLUMN forked")
    assert _is_forked(services, "i1") is True


def test_v41_datastore_upgrades_to_v42_and_carries_old_forks(tmp_path: Path) -> None:
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    path = db_path_for(tmp_path)
    with closing(connect(path, create=False)) as conn:
        for n in ("i1", "i2"):
            InstallLedger(conn).insert(make_item(install_id=n, item_id=f"alex/{n}", name=n))
        conn.execute("ALTER TABLE installed_items DROP COLUMN forked")
        set_meta(conn, db_models.META_SCHEMA_VERSION, "41")
    with closing(sqlite3.connect(tmp_path / "skill_watch.db")) as old, old:
        old.execute("CREATE TABLE forks (install_id TEXT PRIMARY KEY, marked_at TEXT NOT NULL)")
        old.execute("INSERT INTO forks VALUES ('i2', 'x')")
    assert ensure_db_migrated(tmp_path, 4, "0.8.2").status == "ok"
    with closing(connect(path, create=False)) as conn:
        assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION >= 42
        assert dict(conn.execute("SELECT install_id, forked FROM installed_items ORDER BY install_id").fetchall()) == {
            "i1": 0, "i2": 1}
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE installed_items SET forked = 2 WHERE install_id = 'i1'")


def test_autopsy_judges_each_span_against_its_own_locations_disclosure(tmp_path: Path) -> None:
    from dataclasses import replace
    from datetime import datetime, timezone
    from src.core.skill_watch.autopsy import build_autopsy
    fires = SkillFireStore(tmp_path / "f.db")
    main = tmp_path / "p" / "conv.jsonl"
    _write(main, [_fire("2026-09-28T10:00:00Z", "deploy", cwd="/work/mallory"),
                  _bash("2026-09-28T10:00:01Z", "curl x.test"),
                  _d({"type": "user", "timestamp": "2026-09-28T10:00:05Z", "message": {"content": "ok"}})])
    scan_file(fires, str(main), "claude", "default")
    alice = make_item(install_id="ia", item_id="alice/deploy", name="deploy")
    mallory = replace(make_item(install_id="im", item_id="mallory/deploy", name="deploy"),
                      scope="project", project_path="/work/mallory")
    services, _ = _services(tmp_path, [alice, mallory], {"alice/deploy": ["WebFetch"], "mallory/deploy": []})
    out = build_autopsy("deploy", 365, fires, datetime(2026, 9, 29, tzinfo=timezone.utc),
                        attribution=SkillAttribution(services))
    assert out["undisclosed"] == ["network"]
    services2, _ = _services(tmp_path / "b", [alice], {"alice/deploy": ["WebFetch"]})
    out2 = build_autopsy("deploy", 365, fires, datetime(2026, 9, 29, tzinfo=timezone.utc),
                         attribution=SkillAttribution(services2))
    assert out2["undisclosed"] == []

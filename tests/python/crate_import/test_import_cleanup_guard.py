
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

from src.core.crate_import import apply as ap
from src.core.crate_import import cleanup_guard, undo
from src.core.crate_import import hooks as hk
from src.core.crate_import import files_apply
from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.crate_import.plan import build_plan
from src.cplugs.sdk import crate_format as cf
from tests.python.crate_import.test_import_plan import target
from tests.python.crate_import.test_import_project_files import project_crate, restore

DAY_NS = 86_400 * 10**9


def later(monkeypatch: Any, days: int) -> None:
    real = time.time_ns()
    monkeypatch.setattr(cleanup_guard, "time", SimpleNamespace(time_ns=lambda: real + days * DAY_NS))


def conversations(install: Any) -> list:
    return sorted(Path(install.claude, "projects").rglob("*.jsonl"))


def settings_of(install: Any, text: Optional[str]) -> Path:
    path = Path(install.claude, "settings.json")
    if text is not None:
        path.write_text(text, encoding="utf-8")
    return path


def test_the_preview_reads_the_period_and_warns(tmp_path: Path, monkeypatch: Any) -> None:
    crate = project_crate(tmp_path)
    install = target(tmp_path, crate)
    later(monkeypatch, 60)
    settings_of(install, json.dumps({"cleanupPeriodDays": 90, "apiKeyHelper": "sekrit-helper"}))
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, encrypted=False)
    assert plan["cleanup"]["period_days"] == 90 and plan["cleanup"]["needs_guard"] is False
    settings_of(install, None).unlink()
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, encrypted=False)
    assert plan["cleanup"]["period_days"] == 30 and plan["cleanup"]["needs_guard"] is True
    assert plan["cleanup"]["files_older"] >= 1 and plan["cleanup"]["oldest_days"] >= 60 and plan["files"]["restamp"] is True
    assert "sekrit-helper" not in json.dumps(plan)


def test_the_tick_merges_one_key(tmp_path: Path, monkeypatch: Any) -> None:
    crate = project_crate(tmp_path)
    install = target(tmp_path, crate)
    later(monkeypatch, 60)
    original = json.dumps({"theme": "dark", "cleanupPeriodDays": 30, "env": {"A": "1"}})
    path = settings_of(install, original)
    _plan, receipt = restore(crate, install, ImportRequest(keep_conversations=True))
    assert receipt.cleanup["set_to"] == cleanup_guard.KEEP_DAYS and receipt.cleanup["was"] == 30
    assert json.loads(path.read_text()) == {"theme": "dark", "cleanupPeriodDays": 36500, "env": {"A": "1"}}
    assert path.with_name("settings.json.bak").read_text() == original
    (tmp_path / "two").mkdir()
    crate2 = project_crate(tmp_path / "two")
    install2 = target(tmp_path / "two", crate2)
    path2 = settings_of(install2, original)
    restore(crate2, install2, ImportRequest())
    assert path2.read_text() == original and not path2.with_name("settings.json.bak").exists()


def test_an_unreadable_settings_file_blocks_the_tick(tmp_path: Path, monkeypatch: Any) -> None:
    crate = project_crate(tmp_path)
    install = target(tmp_path, crate)
    later(monkeypatch, 60)
    path = settings_of(install, "{not json")
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, ImportRequest(keep_conversations=True), crate_sha256=crate.sha256, encrypted=False)
        unticked = build_plan(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, encrypted=False)
    assert plan["ok"] is False and [b["code"] for b in plan["blockers"]] == ["cleanup_settings_unreadable"]
    assert unticked["ok"] is True and unticked["cleanup"]["refused"]
    assert path.read_text() == "{not json" and not path.with_name("settings.json.bak").exists()


def test_the_undo_puts_the_settings_back(tmp_path: Path, monkeypatch: Any) -> None:
    crate = project_crate(tmp_path)
    install = target(tmp_path, crate)
    later(monkeypatch, 60)
    original = json.dumps({"theme": "dark"})
    path = settings_of(install, original)
    log: list = []

    class Logging(hk.ApplyHooks):
        def undo(self, entry: Dict[str, Any]) -> None:
            log.append(entry)

    hooks = Logging()
    with cf.open_crate(crate.path) as reader:
        request = ImportRequest(keep_conversations=True)
        plan = build_plan(reader, install.env, request, crate_sha256=crate.sha256, encrypted=False)
        ap.apply_import(reader, install.env, request, crate_sha256=crate.sha256, fingerprint=plan["fingerprint"],
                        import_id=new_import_id(), hooks=hooks)
    assert json.loads(path.read_text())["cleanupPeriodDays"] == 36500
    entries = [e for e in log if e.get("op") == undo.OP_SETTINGS]
    assert len(entries) == 1
    report = undo.rollback(entries, files_apply.undo_roots(install.env))
    assert path.read_text() == original and str(path) in report.removed


def test_a_restored_conversation_is_stamped_with_the_restore_time(tmp_path: Path, monkeypatch: Any) -> None:
    crate = project_crate(tmp_path)
    install = target(tmp_path, crate)
    stamp = time.time_ns() + 1000 * DAY_NS
    monkeypatch.setattr(files_apply, "time", SimpleNamespace(time_ns=lambda: stamp))
    restore(crate, install, ImportRequest())
    files = conversations(install)
    assert files, "no conversation was restored"
    for f in files:
        original = next(p for p in Path(crate.world.home, "projects").rglob(f.name))
        assert f.stat().st_mtime_ns == stamp and f.read_bytes() == original.read_bytes(), f


import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import catalog_mod_gates
from src.core.mods import install_gates as gates
from src.core.mods import registry
from src.core.mods.validate_report import parse_report, report_sha
from src.models.catalog_api import InstallConsent
from src.models.catalog_review import ReviewBlock

OK_VERSION = "2.1.295 (Claude Code)"

WORKING_ON = {
    "success": True,
    "strict": True,
    "target": "/x/working-on",
    "manifest": {"file": ".claude-plugin/plugin.json", "type": "manifest", "errors": [], "warnings": [], "notes": [],
                 "gatingHooks": []},
    "contents": [{
        "file": "hooks/hooks.json", "type": "hooks", "errors": [], "warnings": [],
        "notes": [
            "./register.ts hooks: session.start, turn.complete, classic.SessionStart{source=clear|resume|fork}, "
            "ui.render{component=PromptHint}",
            "./register.ts calls: $.clock.after (via schedule), $.model.complete (via refresh), "
            "$.session.messages (via refresh), $.state.get, $.state.set, $.ui.log (via refresh), $.ui.resolve, "
            "$.ui.status",
            "./register.ts: gating hook without .catch",
        ],
        "gatingHooks": [{"module": "./register.ts", "pattern": "classic.PreToolUse", "hook": "handler", "hasCatch": False}],
    }],
    "advice": [],
}


def fake_claude(tmp_path: Path, report: dict, code: int = 0, raw: str = None) -> str:
    (tmp_path / "report.json").write_text(raw if raw is not None else json.dumps(report))
    script = tmp_path / "claude"
    script.write_text(f'#!/bin/sh\ncat "$(dirname "$0")/report.json"\nexit {code}\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def review(verdict=None, status="reviewed", override=None) -> ReviewBlock:
    return ReviewBlock.model_validate({"status": status, "verdict": verdict, **({"override": override} if override else {})})


def refusal(fn, *args, **kwargs) -> str:
    with pytest.raises(gates.ModGateRefusal) as caught:
        fn(*args, **kwargs)
    return caught.value.code


def test_version_gate(tmp_path):
    cli = fake_claude(tmp_path, WORKING_ON)
    assert refusal(gates.evaluate, cli, "2.1.286 (Claude Code)", tmp_path, review("clean")) == "claude_too_old"
    assert refusal(gates.evaluate, cli, "garbage", tmp_path, review("clean")) == "claude_too_old"
    assert refusal(gates.evaluate, None, None, tmp_path, review("clean")) == "claude_missing"
    assert gates.evaluate(cli, "2.1.287 (Claude Code)", tmp_path, review("clean"))[0].claude_version.startswith("2.1.287")


def test_validate_exit_codes(tmp_path):
    failing = {"success": False, "manifest": {"errors": ["No author information provided"]}}
    assert refusal(gates.evaluate, fake_claude(tmp_path, failing, 1), OK_VERSION, tmp_path, review("clean")) == "mod_validate_failed"
    with pytest.raises(gates.ModGateRefusal) as caught:
        gates.evaluate(fake_claude(tmp_path, failing, 1), OK_VERSION, tmp_path, review("clean"))
    assert "No author information provided" in caught.value.detail
    assert refusal(gates.evaluate, fake_claude(tmp_path, {}, 2), OK_VERSION, tmp_path, review("clean")) == "mod_validate_unavailable"
    assert refusal(gates.evaluate, fake_claude(tmp_path, {}, 0, raw="not json"), OK_VERSION, tmp_path, review("clean")) == "mod_validate_unavailable"
    assert refusal(gates.evaluate, str(tmp_path / "missing"), OK_VERSION, tmp_path, review("clean")) == "mod_validate_unavailable"


def test_blocked_verdict_refuses_even_with_override(tmp_path):
    cli = fake_claude(tmp_path, WORKING_ON)
    assert refusal(gates.evaluate, cli, OK_VERSION, tmp_path, review("blocked")) == "review_blocked"
    overridden = review("blocked", override={"reason": "known good"})
    assert refusal(gates.evaluate, cli, OK_VERSION, tmp_path, overridden) == "review_blocked"


def test_flagged_needs_the_extra_tick(tmp_path):
    cli = fake_claude(tmp_path, WORKING_ON)
    for rev, needed in ((review("clean"), False), (review("flagged"), True), (review(None, "unavailable"), True), (None, True)):
        report, sha, ack = gates.evaluate(cli, OK_VERSION, tmp_path, rev)
        assert ack is needed
        base = dict(digest="d", body_sha="b", scripts=True, mod_report_sha=sha)
        assert refusal(gates.check_consent, InstallConsent(**base), sha=sha, flagged_ack_needed=needed) == "consent_required"
        assert refusal(gates.check_consent, None, sha=sha, flagged_ack_needed=needed) == "consent_required"
        trusted = InstallConsent(**base, mod_trust=True)
        if needed:
            assert refusal(gates.check_consent, trusted, sha=sha, flagged_ack_needed=True) == "consent_required"
        gates.check_consent(InstallConsent(**base, mod_trust=True, mod_flagged_ack=True), sha=sha, flagged_ack_needed=needed)


def test_report_changed_between_preview_and_install(tmp_path):
    shown = gates.evaluate(fake_claude(tmp_path, WORKING_ON), OK_VERSION, tmp_path, review("clean"))
    changed = json.loads(json.dumps(WORKING_ON))
    changed["contents"][0]["notes"].append("./register.ts calls: $.fs.write")
    again = gates.evaluate(fake_claude(tmp_path, changed), OK_VERSION, tmp_path, review("clean"))
    assert again[1] != shown[1]
    consent = InstallConsent(digest="d", body_sha="b", scripts=True, mod_trust=True, mod_report_sha=shown[1])
    assert refusal(gates.check_consent, consent, sha=again[1], flagged_ack_needed=False) == "mod_report_changed"
    gates.check_consent(consent, sha=shown[1], flagged_ack_needed=False)


def test_working_on_report_parses():
    report = parse_report(WORKING_ON, OK_VERSION)
    assert report.hooks[0].module == "./register.ts"
    assert report.hooks[0].events == ["session.start", "turn.complete", "classic.SessionStart{source=clear|resume|fork}",
                                      "ui.render{component=PromptHint}"]
    assert "$.model.complete (via refresh)" in report.calls[0].calls and len(report.calls[0].calls) == 8
    assert report.spends_plan_usage is True
    assert report.gating[0].has_catch is False
    assert report.notes_raw == ["./register.ts: gating hook without .catch"]
    assert report_sha(report) == report_sha(parse_report(WORKING_ON, OK_VERSION))
    assert parse_report("nonsense", OK_VERSION).hooks == []


def _world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "mods" / "alpha").mkdir(parents=True)
    settings = home / ".claude" / "settings.json"
    settings.write_text(json.dumps({"keep": 1}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(catalog_mod_gates, "account_settings_files", lambda: ([], "ok"))
    target = SimpleNamespace(path=str(home / ".claude" / "mods" / "alpha"))

    class Ledger:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def targets(self, install_id):
            return [target]

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(
        catalog=SimpleNamespace(ledger=lambda: Ledger())))))
    return request, settings, target


def test_install_registers_and_uninstall_unregisters_first(tmp_path, monkeypatch):
    request, settings, target = _world(tmp_path, monkeypatch)
    assert catalog_mod_gates.register_installed(request, "i1") == "ok"
    assert json.loads(settings.read_text())["env"][registry.ENV_KEY] == target.path
    catalog_mod_gates.unregister_before_uninstall([target])
    assert registry.ENV_KEY not in json.loads(settings.read_text()).get("env", {})
    settings.write_text("{not json")
    with pytest.raises(HTTPException) as caught:
        catalog_mod_gates.unregister_before_uninstall([target])
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "settings_unparseable"
    assert settings.read_text() == "{not json"

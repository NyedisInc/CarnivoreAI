from __future__ import annotations

import json

from scripts.release import deps_gate


def match(sev: str, vid: str = "CVE-1", fixed: list[str] | None = None) -> dict:
    return {"vulnerability": {"id": vid, "severity": sev, "fix": {"state": "fixed" if fixed else "not-fixed", "versions": fixed or []}},
            "artifact": {"name": "foo", "version": "1.0"}}


def entry(by: str) -> dict:
    return {"id": "CVE-1", "package": "foo", "reason": "r", "accepted_by": by, "date": "2026-11-21"}


def test_fixed_high_fails() -> None:
    fails, _ = deps_gate.verdict({"matches": [match("High", fixed=["2.0"])]}, [])
    assert len(fails) == 1 and "foo 1.0 CVE-1 fixed in 2.0" in fails[0]


def test_accepted_high_passes() -> None:
    fails, notes = deps_gate.verdict({"matches": [match("High", fixed=["2.0"])]}, [entry("Alex (example-owner)")])
    assert fails == [] and notes and notes[0].endswith("[accepted]")


def test_pending_operator_is_not_accepted() -> None:
    fails, _ = deps_gate.verdict({"matches": [match("Critical", fixed=["2.0"])]}, [entry("pending operator")])
    assert len(fails) == 1 and "pending operator" in fails[0]


def test_no_fix_and_medium_never_fail() -> None:
    fails, notes = deps_gate.verdict({"matches": [match("High"), match("Medium", "CVE-2", ["2.0"])]}, [])
    assert fails == [] and len(notes) == 2


def test_missing_input_is_exit_2(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(deps_gate.shutil, "which", lambda name: "/bin/true")
    assert deps_gate.main(["--sbom", str(tmp_path / "s.json"), "--root", str(tmp_path)]) == 2
    assert "input missing" in capsys.readouterr().out


def test_missing_tool_is_exit_2(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(deps_gate.shutil, "which", lambda name: None)
    assert deps_gate.main(["--sbom", str(tmp_path / "s.json"), "--root", str(tmp_path)]) == 2


def test_empty_sbom_is_below_floor(tmp_path, monkeypatch) -> None:
    for rel in deps_gate.INPUTS:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    (tmp_path / deps_gate.ACCEPTED).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / deps_gate.ACCEPTED).write_text("[]")
    monkeypatch.setattr(deps_gate.shutil, "which", lambda name: "/bin/true")
    monkeypatch.setattr(deps_gate, "check_db", lambda grype: None)
    monkeypatch.setattr(deps_gate, "run", lambda cmd, timeout: json.dumps({"components": []}))
    assert deps_gate.main(["--sbom", str(tmp_path / "s.json"), "--root", str(tmp_path)]) == 2

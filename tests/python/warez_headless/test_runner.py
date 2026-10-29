
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List

from scripts.crate.errors import ApiError
from scripts.warez import cli, runner
from scripts.warez.runner import Options


class FakeHost:

    def __init__(self, leak: bool = False, roots_missing: bool = False) -> None:
        self.leak, self.roots_missing = leak, roots_missing
        self.catalog = {"nyedis/calming": "theme", "nyedis/working-on": "mod", "external/rea": "plugin"}
        self.ledger: Dict[str, str] = {}
        self.themes: List[str] = ["claude"]
        self.calls: List[str] = []

    def request(self, method: str, path: str, body: Any = None) -> Any:
        self.calls.append(f"{method} {path}")
        if path.endswith("/catalog/items"):
            return {"items": [{"id": i, "kind": k} for i, k in self.catalog.items()]}
        if path.endswith("/catalog/installed") and method == "GET":
            return {"items": [{"item_id": i, "install_id": n, "version": "1.0.0"} for n, i in self.ledger.items()]}
        if path.endswith("/themes"):
            return [{"id": t, "cssVars": {"--a": "1"}} for t in self.themes]
        if path.endswith("/mods"):
            return {"mods": [{"item_id": i, "present": True, "is_mod": True, "state": "on", "registered_in": 1, "groups_total": 1}
                             for i in self.ledger.values() if self.catalog[i] == "mod"]}
        if path.endswith("/install/preview"):
            if self.roots_missing and not body.get("create_roots"):
                raise ApiError("no root", status=409, code="root_absent")
            return {"files": ["a"], "total_bytes": 1, "plan_token": "tok", "requires_consent": self.catalog[body["item_id"]] == "plugin",
                    "digest": "d" * 64, "body_sha": "b" * 64,
                    "mod_report_sha": "r" * 64 if self.catalog[body["item_id"]] == "mod" else None}
        if path.endswith("/catalog/install"):
            if self.catalog[body["item_id"]] == "plugin" and not body.get("consent"):
                raise ApiError("consent", status=409, code="consent_required")
            consent = body.get("consent") or {}
            if self.catalog[body["item_id"]] == "mod" and not (consent.get("mod_trust") and consent.get("mod_report_sha") == "r" * 64):
                raise ApiError("trust tick", status=409, code="consent_required")
            install_id = "ins_" + body["item_id"].split("/")[1]
            self.ledger[install_id] = body["item_id"]
            if self.catalog[body["item_id"]] == "theme":
                self.themes.append("calming")
            return {"install_id": install_id, "version": "1.0.0"}
        if method == "DELETE":
            install_id = path.rsplit("/", 1)[1]
            item = self.ledger.pop(install_id)
            if self.catalog[item] == "theme" and not self.leak:
                self.themes.remove("calming")
            return {"install_id": install_id, "trashed": ["/t/x"], "missing": []}
        raise AssertionError(f"unexpected call {method} {path}")


def statuses(results: List[runner.StepResult]) -> Dict[str, str]:
    return {r.step: r.status for r in results}


def test_a_clean_theme_runs_every_step_in_order_and_restores() -> None:
    host = FakeHost()
    results = runner.run_item(host, "nyedis/calming", "theme")
    assert [r.step for r in results] == list(runner.STEPS)
    assert statuses(results) == {"preview": "pass", "install": "pass", "use": "pass", "uninstall": "pass", "purge": "skip", "restore": "pass"}
    assert host.ledger == {} and host.themes == ["claude"]


def test_a_leftover_after_uninstall_fails_the_restore_step() -> None:
    results = runner.run_item(FakeHost(leak=True), "nyedis/calming", "theme")
    restore = statuses(results)["restore"]
    assert restore == "fail"
    assert "calming" in [r for r in results if r.step == "restore"][0].detail


def test_an_item_already_installed_is_left_alone() -> None:
    host = FakeHost()
    host.ledger["ins_x"] = "nyedis/calming"
    results = runner.run_item(host, "nyedis/calming", "theme")
    assert {r.status for r in results} == {"skip"} and not any(c.startswith("DELETE") for c in host.calls)


def test_a_script_bearing_item_needs_the_consent_flag() -> None:
    assert statuses(runner.run_item(FakeHost(), "external/rea", "plugin"))["install"] == "skip"
    ok = statuses(runner.run_item(FakeHost(), "external/rea", "plugin", Options(consent_scripts=True)))
    assert ok["use"] == "pass" and ok["restore"] == "pass"


def test_a_mod_install_sends_the_trust_tick_and_report_sha_when_consent_is_given() -> None:
    assert statuses(runner.run_item(FakeHost(), "nyedis/working-on", "mod"))["install"] == "skip"
    ok = statuses(runner.run_item(FakeHost(), "nyedis/working-on", "mod", Options(consent_scripts=True)))
    assert ok["install"] == "pass" and ok["use"] == "pass" and ok["restore"] == "pass"


def test_missing_harness_root_is_created_only_when_allowed() -> None:
    assert statuses(runner.run_item(FakeHost(roots_missing=True), "nyedis/working-on", "mod"))["preview"] == "pass"
    off = runner.run_item(FakeHost(roots_missing=True), "nyedis/working-on", "mod", Options(create_roots=False))
    assert [r.step for r in off] == ["preview"] and off[0].status == "fail" and "root_absent" in off[0].detail


def test_cli_prints_one_row_per_step_and_writes_the_report(tmp_path: Path) -> None:
    host, out, err = FakeHost(), io.StringIO(), io.StringIO()
    report = tmp_path / "r.json"
    code = cli.main(["test", "--host", "m1", "--kind", "theme", "--report", str(report)], factory=lambda _a: host, out=out, err=err)
    rows = [line for line in out.getvalue().splitlines() if line.startswith("nyedis/calming")]
    assert code == 0 and len(rows) == len(runner.STEPS) and f"report: {report}" in out.getvalue()
    assert len(json.loads(report.read_text())["results"]) == len(runner.STEPS)


def test_cli_exits_one_when_a_step_fails_and_two_for_an_unknown_item(tmp_path: Path) -> None:
    args = ["test", "--host", "m1", "--report", str(tmp_path / "r.json")]
    assert cli.main(args + ["--item", "nyedis/calming"], factory=lambda _a: FakeHost(leak=True), out=io.StringIO(), err=io.StringIO()) == 1
    err = io.StringIO()
    assert cli.main(args + ["--item", "no/such"], factory=lambda _a: FakeHost(), out=io.StringIO(), err=err) == 2
    assert "no/such" in err.getvalue()

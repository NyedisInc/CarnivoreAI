
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.crate.errors import ApiError
from scripts.warez import cli, update
from scripts.warez.runner import Options, StepResult

OLD, NEW = "1.0.0", "2.0.0"


class FakeUpdateHost:

    def __init__(self, pins: bool = True, badge: bool = True, sticky: bool = False, needs_consent: bool = False) -> None:
        self.pins, self.badge, self.sticky, self.needs_consent = pins, badge, sticky, needs_consent
        self.latest = NEW
        self.row: Optional[Dict[str, Any]] = None
        self.themes: List[str] = ["claude"]
        self.calls: List[str] = []
        self.update_bodies: List[Dict[str, Any]] = []

    def _view(self) -> Dict[str, Any]:
        assert self.row is not None
        return {**self.row, "update_available": self.badge and self.row["version"] != self.latest}

    def request(self, method: str, path: str, body: Any = None) -> Any:
        self.calls.append(f"{method} {path}")
        if path.endswith("/catalog/installed") and method == "GET":
            return {"items": [self._view()] if self.row else []}
        if path.endswith("/themes"):
            return [{"id": t, "cssVars": {"--a": "1"}} for t in self.themes]
        if path.endswith("/install/preview"):
            return {"files": ["a"], "total_bytes": 1, "plan_token": "tok", "requires_consent": False, "digest": "d" * 64, "body_sha": "b" * 64}
        if path.endswith("/catalog/install"):
            version = body.get("version", self.latest) if self.pins else self.latest
            self.row = {"install_id": "ins_calming", "item_id": "nyedis/calming", "version": version, "digest": "dig-" + version, "revision": 1}
            self.themes.append("calming")
            return {"install_id": "ins_calming", "version": version}
        if path.endswith("/update"):
            self.update_bodies.append(body)
            if self.needs_consent and not body.get("consent"):
                raise ApiError("consent", status=409, code="consent_required",
                               detail={"code": "consent_required", "body_sha": "s" * 64, "digest": "d" * 64, "script_files": []})
            if not self.sticky:
                self.row.update(version=self.latest, digest="dig-" + self.latest, revision=self.row["revision"] + 1)
            return {**self.row, "version": self.latest, "digest": "dig-" + self.latest}
        if method == "DELETE":
            self.row = None
            self.themes.remove("calming")
            return {"trashed": ["/t/x"], "missing": []}
        raise AssertionError(f"unexpected call {method} {path}")


def statuses(results: List[StepResult]) -> Dict[str, str]:
    return {r.step: r.status for r in results}


def test_a_clean_update_runs_every_step_and_ends_as_it_started() -> None:
    host = FakeUpdateHost()
    results = update.run_update(host, "nyedis/calming", "theme", OLD)
    assert [r.step for r in results] == list(update.UPDATE_STEPS)
    assert {r.status for r in results} == {"pass", "skip"} and statuses(results)["purge"] == "skip"
    assert statuses(results)["update"] == "pass" and host.row is None and host.themes == ["claude"]
    assert host.update_bodies == [{"expected_revision": 1}]


def test_a_host_that_cannot_pin_a_version_fails_the_install_step() -> None:
    host = FakeUpdateHost(pins=False)
    results = update.run_update(host, "nyedis/calming", "theme", OLD)
    install = [r for r in results if r.step == "install"][-1]
    assert install.status == "fail" and NEW in install.detail and "cannot pin" in install.detail
    assert "update" not in statuses(results) and statuses(results)["restore"] == "pass" and host.row is None


def test_no_badge_fails_the_badge_step_and_still_cleans_up() -> None:
    host = FakeUpdateHost(badge=False)
    got = statuses(update.run_update(host, "nyedis/calming", "theme", OLD))
    assert got["badge"] == "fail" and "update" not in got and got["uninstall"] == "pass" and got["restore"] == "pass"


def test_an_update_that_does_not_move_the_ledger_fails() -> None:
    results = update.run_update(FakeUpdateHost(sticky=True), "nyedis/calming", "theme", OLD)
    step = [r for r in results if r.step == "update"][0]
    assert step.status == "fail" and "digest" in step.detail
    assert statuses(results)["uninstall"] == "pass"


def test_a_consent_sheet_is_answered_with_the_sheet_it_showed() -> None:
    host = FakeUpdateHost(needs_consent=True)
    assert statuses(update.run_update(host, "nyedis/calming", "theme", OLD))["update"] == "pass"
    assert host.update_bodies[-1]["consent"]["body_sha"] == "s" * 64 and host.update_bodies[-1]["consent"]["scripts"] is False


def test_an_item_already_installed_is_left_alone() -> None:
    host = FakeUpdateHost()
    host.request("POST", "/api/v1/catalog/install", {"item_id": "nyedis/calming", "version": OLD})
    results = update.run_update(host, "nyedis/calming", "theme", OLD, Options())
    assert {r.status for r in results} == {"skip"} and not any(c.startswith("DELETE") for c in host.calls)


class CatalogHost(FakeUpdateHost):

    def request(self, method: str, path: str, body: Any = None) -> Any:
        if path.endswith("/catalog/items"):
            return {"items": [{"id": "nyedis/calming", "kind": "theme"}]}
        return super().request(method, path, body)


def test_cli_update_from_runs_the_update_steps(tmp_path: Path) -> None:
    out = io.StringIO()
    args = ["test", "--host", "m1", "--item", "nyedis/calming", "--update-from", OLD, "--report", str(tmp_path / "r.json")]
    code = cli.main(args, factory=lambda _a: CatalogHost(), out=out, err=io.StringIO())
    rows = [ln for ln in out.getvalue().splitlines() if ln.startswith("nyedis/calming")]
    assert code == 0 and len(rows) == len(update.UPDATE_STEPS) and any(" update " in r for r in rows)


def test_cli_update_from_without_an_item_is_a_usage_error(tmp_path: Path) -> None:
    err = io.StringIO()
    code = cli.main(["test", "--host", "m1", "--update-from", OLD], factory=lambda _a: CatalogHost(), out=io.StringIO(), err=err)
    assert code == 2 and "--item" in err.getvalue()

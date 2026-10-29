
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from src.cplugs.sdk import destination_rules as rules
from tests.python.cplugs.owner import turn_on
from tests.python.cplugs.removability import _client


def test_a_good_folder_passes_and_a_blank_one_is_left_to_the_default(tmp_path: Path) -> None:
    good = tmp_path / "crates"
    good.mkdir()
    assert rules.refusals(str(good)) == [] and rules.refusals("   ") == []
    assert rules.refusals(str(tmp_path / "not-made-yet")) == []


def test_relative_symlinked_and_synced_folders_are_refused(tmp_path: Path) -> None:
    assert any("absolute" in p for p in rules.refusals("crates"))
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    assert any("symlink" in p for p in rules.refusals(str(tmp_path / "link")))
    for root in ("~/Library/Mobile Documents", "~/Library/CloudStorage", "~/Dropbox"):
        assert any("synced folder" in p for p in rules.refusals(f"{root}/crates")), root


def test_the_same_disk_advice_names_the_problem_and_stays_quiet_for_blank(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    warning = rules.same_disk_warning(str(tmp_path / "state" / "crates"), tmp_path / "state")
    assert warning and "same disk" in warning
    assert rules.same_disk_warning("", tmp_path) is None


def test_the_host_refuses_a_destination_setting_that_breaks_the_rules(tmp_path: Path) -> None:
    client, host = _client(tmp_path)
    with client:
        turn_on(host, "crate")
        revision = client.get("/api/v1/cplugs/crate").json()["revision"]
        bad = client.put("/api/v1/cplugs/crate", json={"revision": revision, "settings": {"folder": "relative/crates"}})
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "destination_refused"
        synced = client.put("/api/v1/cplugs/crate", json={"revision": revision, "settings": {"secondFolder": "~/Dropbox/crates"}})
        assert synced.status_code == 422 and "synced folder" in synced.json()["detail"]["detail"]
        ok_dir = tmp_path / "second"
        ok_dir.mkdir()
        fine = client.put("/api/v1/cplugs/crate", json={"revision": revision, "settings": {"secondFolder": str(ok_dir)}})
        assert fine.status_code == 200, fine.text
        assert any("same disk" in w["message"] for w in fine.json().get("settings_warnings", []))
        other = client.put("/api/v1/cplugs/crate", json={"revision": fine.json()["revision"], "settings": {}})
        assert other.status_code == 200


def test_a_settings_warning_keeps_its_code_field_and_full_detail_and_leaves_the_permission_warnings_alone(tmp_path: Path) -> None:
    client, host = _client(tmp_path)
    with client:
        turn_on(host, "crate")
        before = client.get("/api/v1/cplugs/crate").json()
        ok_dir = tmp_path / "second"
        ok_dir.mkdir()
        saved = client.put("/api/v1/cplugs/crate", json={"revision": before["revision"], "settings": {"secondFolder": str(ok_dir)}}).json()
        warned = [w for w in saved["settings_warnings"] if w["code"] == "same_disk_app_data"]
        assert len(warned) == 1 and warned[0]["field"] == "secondFolder"
        assert warned[0]["message"] == "same disk as your app data" and str(ok_dir) in warned[0]["detail"] and "lost together" in warned[0]["detail"]
        assert saved["warnings"] == before["warnings"]
        clean = client.put("/api/v1/cplugs/crate", json={"revision": saved["revision"], "settings": {}}).json()
        assert "settings_warnings" not in clean

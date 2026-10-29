
from __future__ import annotations

from pathlib import Path

import pytest
from structlog.testing import capture_logs

from src.core.approvals import beast_lifecycle
from src.core.mcp import beast_mode, beast_store


@pytest.fixture
def switch(monkeypatch: pytest.MonkeyPatch) -> dict:
    state = {"armed": True, "writes": []}

    def write(**kw: object) -> None:
        state["writes"].append(kw)
        state["armed"] = bool(kw.get("enabled"))

    monkeypatch.setattr(beast_mode, "stored_armed", lambda: state["armed"])
    monkeypatch.setattr(beast_store, "write_switch", write)
    return state


def test_a_clean_shutdown_then_a_boot_keeps_an_armed_beast_and_the_marker_vouches_once(tmp_path: Path, switch: dict) -> None:
    beast_lifecycle.stop(tmp_path)
    assert (tmp_path / beast_lifecycle.SHUTDOWN_MARKER).is_file()
    assert beast_lifecycle.start(tmp_path) is False and switch["armed"] and switch["writes"] == [], "a warm boot keeps Beast armed"
    assert not (tmp_path / beast_lifecycle.SHUTDOWN_MARKER).exists(), "the start consumed the marker"
    assert beast_lifecycle.start(tmp_path) is True and switch["armed"] and switch["writes"] == [], "a second start (a crash since) keeps it armed"


def test_a_boot_with_no_marker_keeps_an_armed_beast_armed_and_a_disarmed_one_is_left_alone(tmp_path: Path, switch: dict) -> None:
    with capture_logs() as logs:
        assert beast_lifecycle.start(tmp_path) is True and switch["armed"] and switch["writes"] == []
    assert switch["armed"] and switch["writes"] == [], "nothing is written"
    kept = [e for e in logs if e["event"] == "beastmode_kept_armed"]
    assert len(kept) == 1 and kept[0]["reason"] == "started_without_clean_shutdown" and kept[0]["log_level"] == "warning"
    switch["armed"] = False
    assert beast_lifecycle.start(tmp_path) is False and switch["writes"] == [], "already disarmed: nothing is written"


def test_the_plugins_old_marker_counts_as_a_warm_boot_once_and_is_cleaned_up(tmp_path: Path, switch: dict) -> None:
    legacy = tmp_path / beast_lifecycle.LEGACY_MARKER
    legacy.parent.mkdir(parents=True)
    legacy.write_text("on\n")
    assert beast_lifecycle.start(tmp_path) is False and switch["armed"], "the upgrade restart keeps an armed Beast armed"
    assert not legacy.exists() and not legacy.parent.exists(), "the marker and its now-empty folder are gone"


def test_the_plugins_folder_is_kept_when_it_holds_anything_else(tmp_path: Path, switch: dict) -> None:
    legacy = tmp_path / beast_lifecycle.LEGACY_MARKER
    legacy.parent.mkdir(parents=True)
    (legacy.parent / "other").write_text("x")
    beast_lifecycle.start(tmp_path)
    assert (legacy.parent / "other").is_file()


def test_an_unwritable_marker_still_leaves_the_next_boot_armed_and_writes_nothing(tmp_path: Path, switch: dict) -> None:
    blocker = tmp_path / "state-is-a-file"
    blocker.write_text("x")
    beast_lifecycle.stop(blocker)
    assert beast_lifecycle.start(tmp_path) is True and switch["armed"] and switch["writes"] == []

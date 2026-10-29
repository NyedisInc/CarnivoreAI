
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.approvals.auto_answer import projects, record
from src.core.approvals.extract import extract_dialog
from src.core.session_startup_gate import (
    SCREEN_CHROME, SCREEN_DEV_CHANNELS, SCREEN_TRUST, detect_startup_prompt, named_startup_marker_spans, startup_screen_kind)

SCREENS = Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens"


def text(name: str) -> str:
    return (SCREENS / name).read_text()


@pytest.mark.parametrize("name, kind", [("dev_channels.txt", SCREEN_DEV_CHANNELS), ("dev_channels_80.txt", SCREEN_DEV_CHANNELS),
                                        ("dev_channels_foreign.txt", SCREEN_DEV_CHANNELS), ("chrome_extension.txt", SCREEN_CHROME),
                                        ("trust_dialog.txt", SCREEN_TRUST)])
def test_the_gate_names_each_screen_by_its_own_kind(name: str, kind: str) -> None:
    assert startup_screen_kind(text(name)) == kind
    assert detect_startup_prompt(text(name)) is True
    assert named_startup_marker_spans(text(name))[0][0] == kind


@pytest.mark.parametrize("name, kind", [("dev_channels.txt", SCREEN_DEV_CHANNELS), ("chrome_extension.txt", SCREEN_CHROME),
                                        ("trust_dialog.txt", SCREEN_TRUST)])
def test_the_decoded_dialog_carries_the_startup_kind(name: str, kind: str) -> None:
    assert extract_dialog(text(name), "claude").startup_kind == kind


def test_inside_is_by_path_component_and_realpath(tmp_path: Path) -> None:
    root = tmp_path / "app"
    (root / "src").mkdir(parents=True)
    (tmp_path / "app2").mkdir()
    link = tmp_path / "link"
    os.symlink(root, link)
    assert projects.inside(str(root), [str(root)]) and projects.inside(str(root / "src"), [str(root)])
    assert projects.inside(str(link / "src"), [str(root)])
    assert not projects.inside(str(tmp_path / "app2"), [str(root)])
    assert not projects.inside(str(tmp_path), [str(root)])


def test_a_root_of_slash_or_home_puts_nothing_in_scope(tmp_path: Path) -> None:
    assert not projects.inside(str(tmp_path), ["/"])
    assert not projects.inside(os.path.join(os.path.expanduser("~"), "anything"), [os.path.expanduser("~")])


def test_a_press_leaves_a_history_row_and_a_notification(monkeypatch) -> None:
    rows, events = [], []
    store = SimpleNamespace(record_beast=lambda **kw: rows.append(kw))
    monkeypatch.setattr(record.pending, "get_store", lambda: store)
    monkeypatch.setattr(record.contracts, "emit", lambda event: events.append(event))
    monkeypatch.setattr(record.common, "session_fields", lambda manager, sid: {})
    info = SimpleNamespace(session=SimpleNamespace(id="ses_1"), tmux_session="t1")
    dialog = extract_dialog(text("chrome_extension.txt"), "claude")
    record.record_and_announce(lambda: None)(info, dialog, "chrome_decline", "No, keep browser tools off", "decline_only")
    assert rows[0]["approval_source"] == "auto answered by rule chrome_decline" and rows[0]["action"] == "startup_screen"
    assert rows[0]["args"] == {"rule": "chrome_decline", "screen": "chrome_extension", "evidence": "decline_only"}
    assert events[0].type_id == "session.auto_accepted" and "path" not in events[0].details

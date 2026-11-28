
from __future__ import annotations

import os

from src.core.approvals.carried_trust import IMPORTS_YES_LABEL, YES_LABEL
from tests.python.approvals.test_auto_answer_rules import ELSEWHERE, PROJECT, run, screen

HOME = "/Users/demo"


def test_beast_answers_resumed_imports_home_trust_and_job_folder_trust(monkeypatch) -> None:
    monkeypatch.setattr(os.path, "expanduser", lambda p: HOME if p == "~" else p)
    monkeypatch.setattr(os.path, "realpath", lambda p: p)
    assert run(screen("external_imports_resumed.txt"), readings=3).labels == [IMPORTS_YES_LABEL]
    assert run(screen("external_imports_resumed.txt"), folder=ELSEWHERE).labels == []
    assert run(screen("trust_dialog_home.txt"), folder=HOME, readings=3).labels == [YES_LABEL]
    assert run(screen("trust_dialog_home.txt"), folder=PROJECT).labels == []
    job = "/Users/demo/.carnivore/jobs/folders/app-0123abcd/slot2"
    assert run(screen("trust_dialog.txt", job), folder=job, in_agent_slot=lambda f: f == job).labels == [YES_LABEL]
    assert run(screen("trust_dialog.txt", job), folder=job).labels == []


def test_beast_answers_tall_imports_screen_with_heading_scrolled_off(monkeypatch) -> None:
    monkeypatch.setattr(os.path, "expanduser", lambda p: HOME if p == "~" else p)
    monkeypatch.setattr(os.path, "realpath", lambda p: p)
    assert run(screen("external_imports_tall.txt"), readings=3).labels == [IMPORTS_YES_LABEL]
    assert run(screen("external_imports_tall.txt"), folder=ELSEWHERE).labels == []
    no_rule = screen("external_imports_tall.txt").replace("─" * 100, "")
    assert run(no_rule, readings=3).labels == []

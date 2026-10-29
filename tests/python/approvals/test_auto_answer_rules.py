
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from src.core.approvals.auto_answer import catalog, rules
from src.core.approvals.carried_trust import IMPORTS_YES_LABEL, YES_LABEL
from src.core.approvals.extract import CHROME_ACCEPT_LABEL, CHROME_DECLINE_LABEL, DEV_CHANNELS_ACCEPT, extract_dialog
from src.core.approvals.dev_channels import OUR_FLAG_TOKEN
from src.core.approvals.startup_extract import answer_needs_owner
from src.core.beast_prompts.engine import eligible_dialog
from tests.python.approvals.auto_helpers import FixedPolicy, make_engine

SCREENS = Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens"
AWAITING = "awaiting_startup_prompt"
PROJECT = "/tmp/autoanswer-project"
ELSEWHERE = "/tmp/autoanswer-elsewhere"
NEVER = ["trust_dialog_permissions.txt", "bypass_permissions_warning.txt", "mcp_server_approval.txt", "onboarding_login_method.txt",
         "onboarding_theme.txt", "resume_picker.txt"]


def screen(name: str, folder: Optional[str] = None) -> str:
    text = (SCREENS / name).read_text()
    if folder is not None:
        block = re.search(r"Accessing workspace:\n\n(.*?)\n\n Quick", text, re.S).group(1)
        text = text.replace(block, " " + folder)
    return text


def reading(dialog: Any, pid: Optional[int] = 9) -> SimpleNamespace:
    return SimpleNamespace(stale=False, evidence=SimpleNamespace(dialog=dialog, identity=("s", "n", 1, pid)))


class Presses:

    def __init__(self) -> None:
        self.calls: List[tuple] = []

    async def __call__(self, session_id: str, fingerprint: str, label: str) -> None:
        self.calls.append((session_id, label))

    @property
    def labels(self) -> List[str]:
        return [label for _, label in self.calls]


def run(text: str, *, folder: str = PROJECT, session: str = "ses_1", gate: str = AWAITING, readings: int = 1, **seams: Any) -> Presses:
    presses = Presses()

    async def info(_sid: str) -> Any:
        return SimpleNamespace(session=SimpleNamespace(id=_sid, working_dir=folder), agent_family="claude", startup_gate=gate, tmux_session="t")

    seams.setdefault("in_projects", lambda f: f.endswith("autoanswer-project"))
    seams.setdefault("rows", lambda: [SimpleNamespace(pid=9, ppid=1, command="zsh"), SimpleNamespace(pid=10, ppid=9, command=f"claude {OUR_FLAG_TOKEN}")])
    engine = make_engine(answer=presses, info=info, **seams)
    dialog = extract_dialog(text, "claude")

    async def go() -> None:
        for _ in range(readings):
            task = engine.on_observation(SimpleNamespace(session_id=session), reading(dialog))
            if task is not None:
                await task

    asyncio.run(go())
    return presses


def test_folder_trust_presses_yes_once_in_a_project_folder() -> None:
    assert run(screen("trust_dialog.txt", PROJECT), readings=3).labels == [YES_LABEL]


def test_folder_trust_outside_the_projects_is_left_for_the_owner() -> None:
    assert run(screen("trust_dialog.txt", ELSEWHERE), folder=ELSEWHERE).labels == []


def test_folder_trust_every_scope_presses_any_plain_folder() -> None:
    assert run(screen("trust_dialog.txt", ELSEWHERE), folder=ELSEWHERE, policy=FixedPolicy("every")).labels == [YES_LABEL]


def test_folder_trust_shown_folder_must_be_the_sessions_folder() -> None:
    assert run(screen("trust_dialog.txt", ELSEWHERE), folder=PROJECT).labels == []


def test_folder_trust_waits_for_a_measured_startup_prompt() -> None:
    for gate in ("ready", "unknown", None):
        assert run(screen("trust_dialog.txt", PROJECT), gate=gate).labels == []


def test_a_carried_folder_is_trusted_whatever_the_scope() -> None:
    assert run(screen("trust_dialog.txt", ELSEWHERE), folder=ELSEWHERE, lookup=lambda f: "op").labels == [YES_LABEL]


@pytest.mark.parametrize("name", NEVER)
def test_the_never_list_has_no_rule_and_nothing_is_pressed_even_with_everything_on(name: str) -> None:
    dialog = extract_dialog(screen(name), "claude")
    assert rules.rule_for(dialog) is None
    assert run(screen(name), policy=FixedPolicy("every"), lookup=lambda f: "op", lookup_imports=lambda f: True).labels == []


def test_the_permissions_variant_of_trust_is_a_startup_screen_only_the_owner_answers() -> None:
    dialog = extract_dialog(screen("trust_dialog_permissions.txt"), "claude")
    assert answer_needs_owner(dialog) and eligible_dialog(reading(dialog)) is None


def test_external_imports_in_a_project_folder_presses_yes() -> None:
    assert run(screen("external_imports.txt")).labels == [IMPORTS_YES_LABEL]


def test_external_imports_outside_the_projects_is_left_for_the_owner() -> None:
    assert run(screen("external_imports.txt"), folder=ELSEWHERE).labels == []
    assert run(screen("external_imports.txt"), folder=ELSEWHERE, policy=FixedPolicy("every")).labels == [IMPORTS_YES_LABEL]


def test_a_carried_folder_follows_its_sources_answer_on_imports() -> None:
    assert run(screen("external_imports.txt"), lookup=lambda f: "op", lookup_imports=lambda f: False).labels == []
    assert run(screen("external_imports.txt"), lookup=lambda f: "op", lookup_imports=lambda f: True).labels == [IMPORTS_YES_LABEL]


def test_chrome_presses_no_and_never_yes() -> None:
    for readings in (1, 4):
        presses = run(screen("chrome_extension.txt"), readings=readings)
        assert presses.labels == [CHROME_DECLINE_LABEL] and CHROME_ACCEPT_LABEL not in presses.labels


def test_dev_channels_presses_only_our_channel_on_our_flag() -> None:
    assert run(screen("dev_channels.txt")).labels == [DEV_CHANNELS_ACCEPT]
    assert run(screen("dev_channels_foreign.txt")).labels == []
    assert run(screen("dev_channels.txt"), rows=lambda: [SimpleNamespace(pid=9, ppid=1, command="zsh"),
                                                           SimpleNamespace(pid=10, ppid=9, command="claude --dangerously-load-development-channels server:carnivore")]).labels == []


@pytest.mark.parametrize("name", ["trust_dialog.txt", "external_imports.txt", "chrome_extension.txt", "dev_channels.txt"])
def test_every_box_unticked_answers_nothing_dev_channels_included(name: str) -> None:
    text = screen(name, PROJECT) if name == "trust_dialog.txt" else screen(name)
    assert run(text, policy=FixedPolicy(off=[r.id for r in catalog.RULE_INFOS])).labels == []


@pytest.mark.parametrize("rule_id, name", [(catalog.RULE_FOLDER_TRUST, "trust_dialog.txt"), (catalog.RULE_EXTERNAL_IMPORTS, "external_imports.txt"),
                                           (catalog.RULE_CHROME_DECLINE, "chrome_extension.txt"), (catalog.RULE_DEV_CHANNELS, "dev_channels.txt")])
def test_each_rules_own_switch_silences_only_that_rule(rule_id: str, name: str) -> None:
    text = screen(name, PROJECT) if name == "trust_dialog.txt" else screen(name)
    assert run(text, policy=FixedPolicy(off=[rule_id])).labels == []
    other = [r.id for r in catalog.RULE_INFOS if r.id != rule_id]
    assert run(text, policy=FixedPolicy(off=other)).labels != []


def test_adopted_and_remote_rows_are_never_answered() -> None:
    for session in ("adopted:mine", "remote:peer-1:ses_x"):
        assert run(screen("chrome_extension.txt"), session=session).labels == []


def test_a_new_launch_gets_its_own_press() -> None:
    presses = Presses()
    engine = make_engine(answer=presses)
    dialog = extract_dialog(screen("chrome_extension.txt"), "claude")

    async def go() -> None:
        for pid in (9, 9, 12):
            task = engine.on_observation(SimpleNamespace(session_id="ses_1"), reading(dialog, pid=pid))
            if task is not None:
                await task

    asyncio.run(go())
    assert len(presses.calls) == 2


def test_the_press_is_recorded_with_its_rule_and_evidence() -> None:
    seen: List[tuple] = []
    run(screen("trust_dialog.txt", PROJECT), on_pressed=lambda info, dialog, rule, label, evidence: seen.append((rule, label, evidence)))
    assert seen == [(catalog.RULE_FOLDER_TRUST, YES_LABEL, "project")]


def test_every_rule_label_is_fixed_and_none_is_an_affirmative_chrome_or_bypass_row() -> None:
    assert [r.label for r in rules.RULES] == [DEV_CHANNELS_ACCEPT, YES_LABEL, IMPORTS_YES_LABEL, CHROME_DECLINE_LABEL]
    assert [r.info.id for r in rules.RULES] == [i.id for i in catalog.RULE_INFOS]

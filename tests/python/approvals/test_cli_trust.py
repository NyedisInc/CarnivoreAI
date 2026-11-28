
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from src.core.approvals import cli_trust
from src.core.approvals.auto_answer import catalog, rules
from src.core.approvals.auto_answer.engine import AutoAnswerEngine
from src.core.approvals.dialog_gate import AGY_SCREENS
from src.core.approvals.extract import extract_dialog
from src.core.approvals.startup_extract import answer_needs_owner
from src.core.beast_prompts.engine import eligible_dialog
from tests.python.approvals.auto_helpers import FixedPolicy

FIXTURES = Path(__file__).resolve().parents[2] / "agent_manifests" / "fixtures"
AGY_SCREEN = ("Accessing workspace:\n~/project\n\nDo you trust the contents of this project?\n\nAntigravity CLI requires permission to read, edit, and execute files here.\n\n"
              "> Yes, I trust this folder\n  No, exit\n\n↑/↓ Navigate · enter Confirm\n")


def fixture(name: str, folder: Optional[str] = None) -> str:
    text = (FIXTURES / name).read_text()
    return text if folder is None else text.replace("~/project", folder)


def agy(folder: Path) -> str:
    return AGY_SCREEN.replace("~/project", str(folder))


def gemini(name: str) -> str:
    return fixture("gemini-trust.txt").replace("Trust folder (cloudecode)", f"Trust folder ({name})")


class Presses:

    def __init__(self) -> None:
        self.calls: List[tuple] = []

    async def __call__(self, session_id: str, fingerprint: str, label: str, options: Optional[List[str]] = None) -> None:
        self.calls.append((session_id, label))


@pytest.fixture(autouse=True)
def no_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.core.attention.pane_agent_proof._profile_agent_block", lambda wanted: None)


def run(text: str, cli: str, folder: Path, *, project: Optional[Path] = None, cwd: Optional[str] = "", policy: Any = None, family: str = "custom",
        readings: int = 2) -> List[str]:
    folder = Path(os.path.realpath(folder))
    known = os.path.realpath(project if project is not None else folder)
    presses = Presses()

    async def info(_sid: str) -> Any:
        return SimpleNamespace(session=SimpleNamespace(id=_sid, working_dir=str(folder)), agent_family=family, agent_type=cli, tmux_session="t",
                               startup_gate=None)

    async def pane(_socket: Optional[str], _name: str) -> Optional[str]:
        return str(folder) if cwd == "" else cwd

    seams = rules.Seams(lambda: None, lambda _f: None, lambda _f: False, lambda f: f == known or f.startswith(known + os.sep), pane_cwd=pane)
    engine = AutoAnswerEngine(None, lambda: None, policy=lambda: policy or FixedPolicy(), answer=presses, info=info, seams=seams)
    dialog = cli_trust.decode(text)
    reading = SimpleNamespace(stale=False, evidence=SimpleNamespace(dialog=dialog, identity=("cloude", "t", 1, 9)))

    async def go() -> None:
        for _ in range(readings):
            task = engine.on_observation(SimpleNamespace(session_id="ses_1"), reading)
            if task is not None:
                await task

    asyncio.run(go())
    return [label for _, label in presses.calls]


@pytest.fixture
def app(tmp_path: Path) -> Path:
    path = tmp_path / "app"
    path.mkdir()
    return path


def test_every_known_screen_decodes_to_a_startup_trust_dialog(app: Path) -> None:
    wanted = {"copilot-trust.txt": (cli_trust.CLI_COPILOT, "Yes"), "gemini-trust.txt": (cli_trust.CLI_GEMINI, "Trust folder (cloudecode)"),
              "cursor-trust.txt": (cli_trust.CLI_CURSOR, "Trust this workspace")}
    for name, (cli, safe) in wanted.items():
        dialog = extract_dialog(fixture(name), "custom")
        assert dialog is not None and dialog.startup_kind == "trust" and cli_trust.cli_of(dialog) == cli, name
        assert cli_trust.safe_label(dialog) == safe and dialog.cursor is not None and dialog.rows[dialog.cursor].label
    agy_dialog = extract_dialog(AGY_SCREEN, "custom")
    assert cli_trust.cli_of(agy_dialog) == cli_trust.CLI_AGY and agy_dialog.cursor == 0 and cli_trust.shown_folder(agy_dialog) == "~/project"
    assert cli_trust.safe_label(agy_dialog) == "Yes, I trust this folder"
    assert [r.label for r in agy_dialog.rows] == ["Yes, I trust this folder", "No, exit"]
    gem = cli_trust.decode(gemini("app"))
    assert [r.label for r in gem.rows][0] == "Trust folder (app)" and gem.rows[-1].label == "Don't trust"
    assert cli_trust.safe_label(gem) == "Trust folder (app)"
    assert extract_dialog(AGY_SCREEN, "claude") is None
    assert all(extract_dialog(fixture(n), "claude") is None for n in wanted)
    assert AGY_SCREENS[2] in AGY_SCREEN.lower()
    for broken in (AGY_SCREEN.replace("Accessing workspace:\n", ""), AGY_SCREEN.replace("↑/↓ Navigate · enter Confirm\n", ""),
                   AGY_SCREEN.replace("Antigravity CLI requires permission to read, edit, and execute files here.", "Something else entirely.")):
        assert cli_trust.decode(broken) is None


def test_copilot_row_set_is_exact_and_remember_is_never_the_safe_row() -> None:
    dialog = cli_trust.decode(fixture("copilot-trust.txt"))
    assert [r.label for r in dialog.rows] == ["Yes", "Yes, and remember this folder for future sessions", "No (Esc)"]
    assert cli_trust.safe_label(dialog) == "Yes" and cli_trust.shown_folder(dialog) == "~/project"
    assert answer_needs_owner(dialog) and eligible_dialog(SimpleNamespace(stale=False, evidence=SimpleNamespace(dialog=dialog))) is None


def test_a_stale_or_altered_screen_does_not_decode() -> None:
    text = fixture("copilot-trust.txt")
    assert cli_trust.decode(text + "\n > the box above is old, the agent is working now\n") is None
    assert cli_trust.decode(text.replace("❯ 1. Yes", "  1. Yes")) is None
    assert cli_trust.decode(text.replace("2. Yes, and remember", "2. Yes, always")) is None
    assert cli_trust.decode(fixture("gemini-trust.txt").replace("● 1.", "  1.")) is None
    assert cli_trust.decode(AGY_SCREEN.replace("> Yes", "  Yes")) is None


def test_beast_on_presses_copilots_session_only_yes_when_the_screen_names_the_sessions_folder(app: Path) -> None:
    assert run(fixture("copilot-trust.txt", os.path.realpath(app)), "copilot", app) == ["Yes"]


def test_beast_on_presses_exactly_the_yes_row_of_gemini_cursor_and_agy(app: Path) -> None:
    assert run(fixture("cursor-trust.txt", os.path.realpath(app)), "cursor", app) == ["Trust this workspace"]
    assert run(gemini("app"), "gemini", app) == ["Trust folder (app)"]
    assert run(agy(Path(os.path.realpath(app))), "agy", app) == ["Yes, I trust this folder"]


def test_a_remembered_yes_cli_still_presses_nothing_outside_its_guards(app: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    off = FixedPolicy(off=[catalog.RULE_CLI_TRUST])
    agy_screen = agy(Path(os.path.realpath(app)))
    assert run(agy_screen, "agy", app, policy=off) == []
    assert run(agy_screen, "agy", app, project=other) == []
    assert run(agy(Path(os.path.realpath(other))), "agy", app) == []
    assert run(agy_screen, "gemini", app) == [] and run(agy_screen, "cursor", app) == []
    assert run(gemini("other"), "gemini", app) == []
    assert run(gemini("app"), "gemini", app, cwd=None) == []
    assert run(gemini("app"), "gemini", app, cwd=str(other)) == []
    assert run(fixture("cursor-trust.txt", os.path.realpath(other)), "cursor", app) == []
    assert run(agy(Path("/")), "agy", Path("/"), policy=FixedPolicy("every")) == []


def test_a_folder_below_a_known_project_is_in_scope(app: Path) -> None:
    sub = app / "pkg"
    sub.mkdir()
    assert run(fixture("copilot-trust.txt", os.path.realpath(sub)), "copilot", sub, project=app) == ["Yes"]


def test_beast_off_presses_nothing(app: Path) -> None:
    off = FixedPolicy(off=[catalog.RULE_CLI_TRUST])
    assert run(fixture("copilot-trust.txt", os.path.realpath(app)), "copilot", app, policy=off) == []


def test_the_grid_row_is_beast_on_only_by_default() -> None:
    from src.core.approvals.beast_grid import row_for

    row = row_for(catalog.RULE_CLI_TRUST)
    assert (row.default_off, row.default_on) == (False, True)


def test_a_screen_of_another_cli_is_never_pressed(app: Path) -> None:
    copilot = fixture("copilot-trust.txt", os.path.realpath(app))
    assert run(copilot, "agy", app) == []
    assert run(copilot, "gemini", app) == []
    assert run(copilot, "nonsense", app) == []
    assert run(copilot, "copilot", app, family="claude") == []


def test_a_folder_outside_every_project_or_another_folder_is_never_pressed(app: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    assert run(fixture("copilot-trust.txt", os.path.realpath(app)), "copilot", app, project=other) == []
    assert run(fixture("copilot-trust.txt", os.path.realpath(other)), "copilot", app) == []
    assert run(fixture("copilot-trust.txt", "~/definitely-not-here"), "copilot", app) == []


def test_an_unread_cwd_presses_nothing_and_every_scope_never_reaches_home_or_root(app: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    every = FixedPolicy("every")
    named = lambda folder: fixture("copilot-trust.txt", os.path.realpath(folder))  # noqa: E731
    assert run(named(app), "copilot", app, policy=every) == ["Yes"]
    monkeypatch.setenv("HOME", os.path.realpath(app))
    assert run(named(app), "copilot", app, policy=every) == []
    assert run(named("/"), "copilot", Path("/"), policy=every) == []


def test_claudes_own_trust_rules_are_unchanged() -> None:
    dialog = extract_dialog((FIXTURES.parents[1] / "fixtures" / "startup_screens" / "trust_dialog.txt").read_text(), "claude")
    assert rules.rule_for(dialog).info.id == catalog.RULE_FOLDER_TRUST and cli_trust.cli_of(dialog) is None
    assert rules.rules_for(cli_trust.decode(fixture("copilot-trust.txt")))[0].info.id == catalog.RULE_CLI_TRUST


def test_the_watcher_reader_puts_the_trust_screen_on_a_custom_rows_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    import time
    from datetime import datetime, timezone

    from src.core import attention_reader as reader_module
    from src.core.attention.watcher import WatchTarget
    from src.core.attention_reader import AttentionEvidenceReader
    from src.core.session_instance_index import InstanceIndex
    from src.core.session_status_map import StatusMap

    row = {"pane_id": "%1", "pid": 7, "created_at_epoch": int(time.time()) - 60, "pane_dead": "0", "window_activity": 100, "pane_width": 80,
           "pane_height": 24, "status": "running", "pane_current_path": "/x", "pane_current_command": "zsh"}
    screens = {"text": fixture("copilot-trust.txt", "/x")}
    manager = SimpleNamespace(
        _build_tmux_status_map=lambda: StatusMap({"cloude_a": dict(row)}, complete=True, socket="cloude"),
        _identity_for_instance=lambda name, epoch: {"agent_type": "custom"},
        _instance_index_for_listing=lambda *, socket, names: InstanceIndex(), tmux_socket_name=lambda: "cloude", _wrappers_reader=lambda: [],
        _registry=SimpleNamespace(sessions={"s": SimpleNamespace(agent_type="custom", working_dir=None)}, backends={"s": SimpleNamespace(socket_name="cloude")}))
    monkeypatch.setattr(reader_module, "read_registry_index", lambda: {})
    monkeypatch.setattr(reader_module, "read_instance_row", lambda *a, **k: {})
    monkeypatch.setattr(AttentionEvidenceReader, "_process_parents", lambda *args: {})
    monkeypatch.setattr(AttentionEvidenceReader, "_process_snapshot", lambda *args: SimpleNamespace(parents={8: 7}, commands={8: "/h/bin/copilot"}))
    monkeypatch.setattr(AttentionEvidenceReader, "_capture", staticmethod(lambda socket, name, history=0, row=None: screens["text"]))
    reader = AttentionEvidenceReader(manager, lambda sid: ("cloude_a", row["created_at_epoch"]))
    evidence = reader(WatchTarget("s", "cloude_a@1"), datetime.now(timezone.utc))
    assert evidence.agent_family == "custom" and evidence.manifest is not None and evidence.manifest.cli == "copilot"
    assert cli_trust.cli_of(evidence.dialog) == cli_trust.CLI_COPILOT
    screens["text"] = "copilot is working\n"
    row["window_activity"] = 200
    assert reader(WatchTarget("s", "cloude_a@1"), datetime.now(timezone.utc)).dialog is None

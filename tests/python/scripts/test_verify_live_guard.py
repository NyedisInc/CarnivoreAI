
from __future__ import annotations

import importlib.util
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from scripts.lib.verify_harness import live_target_refusal, refuse_live_target

ROOT = Path(__file__).resolve().parents[3]
GUARDED = [
    "agent_kebab_menus", "drawer_colours", "group_icon", "layouts_drawer", "effort_workflow", "drawer_heading_kebab",
    "blueprints", "layout_parking", "focus_edge", "drawer_final", "home_header_span",
]


@pytest.mark.parametrize("base", ["http://127.0.0.1:8000", "http://localhost:8000/"])
def test_the_live_port_is_refused(base: str) -> None:
    assert live_target_refusal(Namespace(base=base))


@pytest.mark.parametrize("socket", ["cloude", "carnivore"])
def test_both_live_sockets_are_refused(socket: str) -> None:
    assert live_target_refusal(Namespace(base="http://127.0.0.1:5101", socket=socket))


def test_the_live_state_dir_is_refused() -> None:
    live = str(Path("~/Library/Application Support/Carnivore").expanduser())
    assert live_target_refusal(Namespace(base="http://127.0.0.1:5101", state_dir=live))


def test_a_throwaway_slot_passes(tmp_path: Path) -> None:
    args = Namespace(base="http://127.0.0.1:5101", socket="cloude-test1", state_dir=str(tmp_path))
    assert live_target_refusal(args) is None
    assert refuse_live_target(args) is None


def test_refusal_returns_exit_2_and_prints(capsys: pytest.CaptureFixture) -> None:
    assert refuse_live_target(Namespace(base="http://127.0.0.1:8000")) == 2
    assert "CANNOT DETERMINE" in capsys.readouterr().out


@pytest.mark.parametrize("name", GUARDED)
def test_every_mutating_verify_script_calls_the_shared_guard(name: str) -> None:
    source = (ROOT / "scripts" / f"verify_{name}.py").read_text()
    calls = [c for c in ("refuse_live_target(args)", "require_slot(args)") if c in source]
    assert calls, f"verify_{name}.py calls neither guard"
    assert source.index(calls[0]) > source.index("parse_args()")


def test_the_guard_holds_under_python_dash_O() -> None:
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from argparse import Namespace\nfrom scripts.lib.verify_harness import refuse_live_target\n"
            "print(refuse_live_target(Namespace(base='http://127.0.0.1:8000')))" % str(ROOT))
    out = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, text=True, timeout=30, cwd=ROOT)
    assert out.stdout.strip().endswith("2"), out.stderr

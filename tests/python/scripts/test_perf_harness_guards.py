
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PERF = Path(__file__).resolve().parents[3] / "scripts" / "perf"
sys.path.insert(0, str(PERF))

import perf_env  # noqa: E402
import run_baseline  # noqa: E402
from src.core import product_identity  # noqa: E402
from tmux_socket_file import LIVE_SOCKET_NAMES, LiveSocketRefused, refuse_live_socket  # noqa: E402


def test_live_socket_names_match_product_identity() -> None:
    assert set(LIVE_SOCKET_NAMES) == {product_identity.TMUX_SOCKET_NAME, *product_identity.LEGACY_TMUX_SOCKET_NAMES}


@pytest.mark.parametrize("name", ["cloude", "carnivore", ""])
def test_a_live_or_empty_socket_name_is_refused(name: str) -> None:
    with pytest.raises(LiveSocketRefused):
        refuse_live_socket(name)


@pytest.mark.parametrize("name", ["cloude", "carnivore"])
def test_perfserver_refuses_a_live_socket_before_creating_anything(name: str) -> None:
    with pytest.raises(LiveSocketRefused):
        perf_env.PerfServer(tmux_socket_name=name)


def test_the_guard_survives_python_dash_O() -> None:
    code = (
        "import sys; sys.path.insert(0, %r); from tmux_socket_file import refuse_live_socket, LiveSocketRefused\n"
        "try:\n    refuse_live_socket('cloude')\nexcept LiveSocketRefused:\n    print('refused')\n" % str(PERF)
    )
    out = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "refused", out.stderr


def test_no_assert_guards_remain_in_perf_env() -> None:
    assert "assert self.tmux_socket" not in (PERF / "perf_env.py").read_text()
    assert not hasattr(perf_env, "assert_no_live_socket_named")


def test_db_cost_reads_carnivore_db_and_a_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(run_baseline.DbMissing):
        run_baseline._measure_db_cost(tmp_path, 3)
    import sqlite3

    with sqlite3.connect(tmp_path / product_identity.DB_FILENAME) as conn:
        conn.execute("CREATE TABLE sessions (id INTEGER)")
    assert run_baseline._measure_db_cost(tmp_path, 3) >= 0.0


def test_out_and_raw_json_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_baseline.py"])
    with pytest.raises(SystemExit) as exc:
        run_baseline.main()
    assert exc.value.code == 2


def test_the_report_header_carries_the_run_date_and_revision() -> None:
    doc, _ = run_baseline.build_report([])
    assert doc.startswith("# Performance baseline, 20")
    assert "2026-09-10" not in doc.splitlines()[0]


def test_the_toast_probe_targets_rendered_toasts_not_the_container() -> None:
    assert "#toast-container .toast" in run_baseline.TOAST_COUNT_JS
    assert "[class*=" not in run_baseline.TOAST_COUNT_JS


NODE_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
let rows = [''];
const term = { rows: 1, buffer: { active: { viewportY: 0, getLine: (i) => ({ translateToString: () => rows[i] }) } },
               onRender: (cb) => { term._cb = cb; } };
function FakeSocket() {}
const win = { WebSocket: FakeSocket, TerminalController: { term, _sessionId: () => 's' }, addEventListener() {} };
const ctx = { window: win, document: { addEventListener() {} }, performance: { now: () => 1 }, URL, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
win.__armRenderHook();
rows = ['$ ab']; // the prompt and old output already hold 'a' and 'b'
win.__armEcho();
const out = {};
term._cb(); // a cursor-blink repaint: same text
out.afterBlink = win.__echoSnapshot('a').rendered;
rows = ['$ aba']; // the echoed character arrives
term._cb();
out.afterEcho = win.__echoSnapshot('a').rendered;
console.log(JSON.stringify(out));
"""


def test_a_repaint_of_existing_text_is_not_an_echo(tmp_path: Path) -> None:
    script = tmp_path / "harness.js"
    script.write_text(NODE_HARNESS)
    out = subprocess.run(["node", str(script), str(PERF / "perf_instrument.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"afterBlink": False, "afterEcho": True}

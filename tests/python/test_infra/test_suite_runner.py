import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts" / "lib" / "suite_runner.py"


def _env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST", "CLOUDE_SUITE"))}
    env.update(extra)
    return env


def test_stalled_log_is_killed_with_97_and_names_the_stuck_test(tmp_path):
    state, log = tmp_path / "state", tmp_path / "suite.log"
    state.mkdir()
    (state / "gw3.cur").write_text("tests/test_x.py::test_stuck")
    script = f"""
import pathlib, time
pathlib.Path({str(state / 'gw3.cur')!r}).write_text('tests/test_x.py::test_stuck')
print('== pass 1 of 2: fake', flush=True)
time.sleep(600)
"""
    res = subprocess.run(
        [sys.executable, str(RUNNER), "--log", str(log), "--state-dir", str(state), "--", sys.executable, "-c", script],
        env=_env(CLOUDE_SUITE_STALL_MINUTES="0.03", CLOUDE_SUITE_POLL_SECONDS="0.2"),
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 97, res.stderr
    assert "gw3: tests/test_x.py::test_stuck" in res.stderr
    assert "gw3: tests/test_x.py::test_stuck" in log.read_text()


def test_wall_clock_cap_exits_98(tmp_path):
    script = "import time\nprint('== pass 1 of 2', flush=True)\nwhile True:\n    print('.', flush=True); time.sleep(0.1)\n"
    res = subprocess.run(
        [sys.executable, str(RUNNER), "--log", str(tmp_path / "l"), "--state-dir", str(tmp_path / "s"), "--", sys.executable, "-c", script],
        env=_env(CLOUDE_SUITE_MAX_MINUTES="0.03", CLOUDE_SUITE_POLL_SECONDS="0.2"),
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 98, res.stderr


def test_failures_file_gets_failed_and_error_ids_as_they_happen(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n"
        "def test_ok(): pass\n"
        "def test_bad(): assert False\n"
        "@pytest.fixture\n"
        "def boom(): raise RuntimeError('x')\n"
        "def test_err(boom): pass\n"
    )
    state, fails = tmp_path / "state", tmp_path / "fails.txt"
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-n", "2", "-p", "suite_progress", "-p", "no:cacheprovider", str(tmp_path / "test_sample.py")],
        env=_env(PYTHONPATH=str(ROOT / "scripts" / "lib"), CLOUDE_SUITE_STATE_DIR=str(state), CLOUDE_SUITE_FAILURES_FILE=str(fails)),
        capture_output=True, text=True, cwd=tmp_path, timeout=120,
    )
    assert res.returncode == 1, res.stdout + res.stderr
    lines = sorted(fails.read_text().splitlines(), key=lambda l: l.split("::")[-1])
    assert [l.split("::")[-1] for l in lines] == ["test_bad", "test_err"]
    assert lines[0].startswith("FAILED ") and lines[1].startswith("ERROR ")
    assert not list(state.glob("*.cur"))
    assert list(state.glob("*.pid"))


sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import suite_rerun  # noqa: E402

_FAIL_LOG = "== pass 1 of 2\nrun-tests.sh: FAIL (parallel pass 1, serial pass 0)\n"
_IDS = ["tests/a.py::t[x y]", "tests/b.py::t2", "tests/c.py::t3"]


def _decide(rc, log, ids, cap=10, bad=()):
    asked = []

    def run_one(i):
        asked.append(i)
        return i not in bad

    return suite_rerun.decide(rc, log, ids, cap, run_one), asked


def test_rerun_rule_flakes_real_failures_cap_and_stall_exits():
    out, asked = _decide(1, _FAIL_LOG, _IDS)
    assert (out.rc, out.flakes, out.real, asked) == (0, _IDS, [], _IDS)
    out, _ = _decide(1, _FAIL_LOG, _IDS, bad={_IDS[1]})
    assert (out.rc, out.flakes, out.real) == (1, [_IDS[0], _IDS[2]], [_IDS[1]])
    out, asked = _decide(1, _FAIL_LOG, _IDS, cap=2)
    assert (out.rc, out.reran, asked) == (1, False, [])
    for code in (97, 98):
        out, asked = _decide(code, _FAIL_LOG, _IDS)
        assert (out.rc, out.reran, asked) == (code, False, [])
    out, asked = _decide(1, "run-tests.sh: FAIL (parallel pass 2, serial pass 0)\n", _IDS)
    assert (out.rc, asked) == (1, [])
    assert suite_rerun.parse_ids("FAILED a b\nERROR c\nFAILED a b\n") == ["a b", "c"]

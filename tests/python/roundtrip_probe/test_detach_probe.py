
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROBE = Path(__file__).resolve().parents[3] / "scripts" / "ci" / "roundtrip_lib" / "detach_probe.py"


@pytest.fixture()
def probe():
    spec = importlib.util.spec_from_file_location("detach_probe_under_test", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_sequence_runs_on_the_current_api_and_reads_the_id_back(tmp_path) -> None:
    repo = Path(__file__).resolve().parents[3]
    env = {**os.environ, "CARNIVORE_STATE_DIR": str(tmp_path / "state"), "LOG_DIRECTORY": str(tmp_path / "logs")}
    done = subprocess.run([sys.executable, str(PROBE)], cwd=repo, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["persisted_after_detach"] == "roundtrip-b"
    assert str(tmp_path) in result["resolved"], "the probe must stay inside the test's state dir"


def test_an_api_that_moved_is_reported_as_an_error_not_a_value(probe, monkeypatch, capsys) -> None:
    def moved(_install):
        raise AttributeError("'SessionManager' object has no attribute 'current_session'")

    monkeypatch.setattr(probe, "run_detach_sequence", moved)
    assert probe.main() == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "current_session" in out["error"]
    assert "persisted_after_detach" not in out

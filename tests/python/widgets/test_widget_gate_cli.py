
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

from scripts.widgets import harness

RECORDS = json.loads((Path(harness.REPO) / "src" / "data" / "widget-contracts.json").read_text(encoding="utf-8"))["widgets"]


def run_gate(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "scripts.widgets.gate", "--no-build", *args], cwd=harness.REPO,
                          capture_output=True, text=True, timeout=600, check=False)


def test_a_broken_widget_fails_the_command_with_a_reason_and_a_red_table(page_and_base, tmp_path: Path) -> None:
    broken = {**copy.deepcopy(next(r for r in RECORDS if r["id"] == "core.keep-awake")), "id": "broken.widget"}
    records = tmp_path / "records.json"
    records.write_text(json.dumps({"widgets": [broken]}), encoding="utf-8")
    out = tmp_path / "out"
    done = run_gate("--records", str(records), "--out", str(out))
    assert done.returncode == 1, done.stdout + done.stderr
    gate = json.loads((out / "broken.widget.gate.json").read_text(encoding="utf-8"))
    assert gate["ok"] is False and any("harness draws no widget with this id" in f for f in gate["failures"]), gate["failures"]
    table = json.loads((out / "fit-table.json").read_text(encoding="utf-8"))
    assert table["widgets"][0]["widget"] == "broken.widget" and table["widgets"][0]["ok"] is False
    assert table["counts"]["pass"] == 0


def test_an_unreadable_records_file_cannot_determine(tmp_path: Path) -> None:
    done = run_gate("--records", str(tmp_path / "missing.json"), "--out", str(tmp_path / "out"))
    assert done.returncode == 2 and "CANNOT DETERMINE" in done.stderr

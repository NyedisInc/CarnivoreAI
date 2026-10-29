from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / "scripts" / "upgrade_snapshot.py"

_PROGRAM = f"""
import importlib.util, os, sys
sys.path.insert(0, {str(ROOT)!r})
spec = importlib.util.spec_from_file_location("upgrade_snapshot", {str(SNAPSHOT)!r})
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
state, how = mod._state_dir(mod.Path(os.environ["FAKE_INSTALL"]))
print(state, "|", how)
"""


def _resolve(home: Path) -> str:
    install = home / "empty-install"
    install.mkdir(exist_ok=True)
    env = {"HOME": str(home), "FAKE_INSTALL": str(install), "PATH": "/usr/bin:/bin"}
    prog = _PROGRAM.replace(
        "state, how =",
        "import src.config as _c\n_c.settings = None\nstate, how =",
    )
    out = subprocess.run(
        [sys.executable, "-c", prog], capture_output=True, text=True, env=env, cwd=home
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip().splitlines()[-1]


def test_current_carnivore_dir_is_found_when_config_will_not_import(tmp_path):
    support = tmp_path / "Library" / "Application Support"
    (support / "Carnivore").mkdir(parents=True)
    line = _resolve(tmp_path)
    assert line.startswith(str(support / "Carnivore")), line


def test_legacy_cloudecode_dir_is_still_found(tmp_path):
    support = tmp_path / "Library" / "Application Support"
    (support / "CloudeCode").mkdir(parents=True)
    line = _resolve(tmp_path)
    assert line.startswith(str(support / "CloudeCode")), line

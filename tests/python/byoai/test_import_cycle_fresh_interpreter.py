
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("module", ["src.config.settings", "src.config.byoai", "src.core.byoai.gateway"])
def test_module_imports_first_in_a_fresh_interpreter(module):
    result = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(REPO)!r}); import {module}"],
                            capture_output=True, text=True, timeout=120, cwd=REPO)
    assert result.returncode == 0, result.stderr[-800:]

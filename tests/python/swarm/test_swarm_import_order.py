import subprocess
import sys

import pytest

STANDALONE_MODULES = (
    "src.core.swarm.body_create",
    "src.core.swarm.say",
    "src.core.swarm.body",
    "src.core.swarm.project_agent",
    "src.core.swarm.company_agent",
    "src.core.swarm.membership",
    "src.plugins.taskmanager.routes_ask",
    "src.plugins.taskmanager.routes_common",
    "src.plugins.reviewboard.routes_live",
    "src.plugins.reviewboard.routes_common",
)


@pytest.mark.parametrize("module", STANDALONE_MODULES)
def test_module_imports_first(module: str) -> None:
    done = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr[-600:]

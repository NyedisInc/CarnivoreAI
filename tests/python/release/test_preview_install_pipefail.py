
from __future__ import annotations

import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "release" / "preview-install.sh"
RUNS = 50
OLD_AWK = """awk 'NR == 1 { sub(/^worktree /, ""); print; exit }'"""


def _script_awk(marker: str) -> str:
    line = next(l for l in SCRIPT.read_text().splitlines() if marker in l)
    return re.search(r"awk .*?'\)\"", line).group(0)[:-2]


def _run(tmp_path: Path, awk_cmd: str) -> list[subprocess.CompletedProcess]:
    fake = tmp_path / "git"
    fake.write_text(
        "#!/bin/bash\nfor i in $(seq 1 600); do echo \"worktree /first/path$i-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\"; done\n"
    )
    fake.chmod(0o755)
    cmd = f'set -euo pipefail; main="$(git -C /x worktree list --porcelain | {awk_cmd})"; echo "$main"'
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin"}
    return [
        subprocess.run(["/bin/bash", "-c", cmd], env=env, capture_output=True, text=True)
        for _ in range(RUNS)
    ]


def test_worktree_list_pipeline_survives_pipefail(tmp_path: Path) -> None:
    runs = _run(tmp_path, _script_awk("worktree list --porcelain"))
    assert all(r.returncode == 0 for r in runs)
    assert {r.stdout.strip() for r in runs} == {"/first/path1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}


def test_old_early_exit_awk_is_flaky(tmp_path: Path) -> None:
    runs = _run(tmp_path, OLD_AWK)
    assert any(r.returncode != 0 for r in runs)

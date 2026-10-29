
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

REAL = Path(__file__).resolve().parents[3] / "scripts" / "xterm-vendor" / "fetch.sh"
GOOD = b"good bytes\n"


def _setup(tmp_path: Path, bad_file: str | None) -> tuple[Path, dict[str, str]]:
    script_dir = tmp_path / "scripts" / "xterm-vendor"
    script_dir.mkdir(parents=True)
    pinned = re.sub(r"\|[0-9a-f]{64}$", "|" + hashlib.sha256(GOOD).hexdigest(), REAL.read_text(), flags=re.M)
    (script_dir / "fetch.sh").write_text(pinned)
    out = tmp_path / "client" / "vendor" / "xterm"
    out.mkdir(parents=True)
    for name in ("xterm.css", "xterm.js"):
        (out / name).write_text("committed\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/bin/bash\n"
        'while [ $# -gt 0 ]; do case "$1" in -o) dest="$2"; shift 2;; *) url="$1"; shift;; esac; done\n'
        f'if [ "$(basename "$url")" = "{bad_file}" ]; then printf "tampered\\n" > "$dest"; else printf "good bytes\\n" > "$dest"; fi\n'
    )
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    return script_dir / "fetch.sh", dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", TMPDIR=str(tmp_path))


def test_green_control_installs_all_six(tmp_path: Path) -> None:
    script, env = _setup(tmp_path, bad_file=None)
    done = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    out = tmp_path / "client" / "vendor" / "xterm"
    assert sorted(p.name for p in out.iterdir()) == sorted(
        ["xterm.css", "xterm.js", "xterm-addon-fit.js", "xterm-addon-webgl.js", "xterm-addon-unicode11.js", "xterm-addon-search.js"])
    assert (out / "xterm.js").read_bytes() == GOOD


def test_a_mismatch_leaves_the_committed_tree_untouched(tmp_path: Path) -> None:
    script, env = _setup(tmp_path, bad_file="xterm-addon-search.js")
    done = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 1 and "sha256 mismatch" in done.stderr, done.stdout + done.stderr
    out = tmp_path / "client" / "vendor" / "xterm"
    assert sorted(p.name for p in out.iterdir()) == ["xterm.css", "xterm.js"]
    assert (out / "xterm.css").read_text() == "committed\n"
    assert not list(tmp_path.glob("xterm-vendor.*")), "the staging directory is cleaned up"

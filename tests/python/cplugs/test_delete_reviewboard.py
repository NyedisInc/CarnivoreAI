
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIRS = ("src/plugins/reviewboard", "web/src/plugins/reviewboard")
OWN_NAMES = re.compile(r"reviewboard|publicboard", re.I)


def test_the_cplugs_package_imports_with_the_review_board_folder_gone(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    shutil.copytree(ROOT / "src", tree / "src", ignore=shutil.ignore_patterns("__pycache__", "reviewboard"))
    shutil.copy(ROOT / "config.example.json", tree / "config.example.json")
    code = "import src.plugins.registry as r; ids=[d.id for d in r.CPLUGS]; assert 'reviewboard' not in ids and 'publicboard' not in ids and 'huddle' in ids, ids; print(len(ids))"
    done = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(tree)!r}); {code}"], capture_output=True, text=True, cwd=tree, timeout=120)
    assert done.returncode == 0, done.stderr[-1500:]


def test_no_file_outside_the_plugin_names_its_visitor_bundle() -> None:
    offenders = []
    for base in ("src", "web", "client", "scripts"):
        for path in (ROOT / base).rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".svelte", ".js", ".html", ".mjs", ".json"}:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith(PLUGIN_DIRS) or "/node_modules/" in rel or "/dist/" in rel or rel.startswith(("tests/", "web/node_modules")):
                continue
            if re.search(r"dist/(public|review)board[-.]?(public)?\.(js|css)", path.read_text(errors="ignore")):
                offenders.append(rel)
    assert offenders == [], offenders

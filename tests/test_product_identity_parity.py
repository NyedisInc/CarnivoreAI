
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.core import product_identity as pid

REPO_ROOT = Path(__file__).resolve().parent.parent

CONSTANT_NAMES = [
    "PRODUCT_NAME",
    "TMUX_SOCKET_NAME",
    "TMUX_SESSION_PREFIX",
    "DB_FILENAME",
    "DB_BACKUP_PREFIX",
    "STATE_DIR_NAME",
    "MENUBAR_STATE_DIR_NAME",
    "BUNDLE_ID",
    "ENV_PREFIX",
    "UPLOAD_DIR_NAME",
    "BROWSER_KEY_PREFIX",
    "RELEASE_REPO",
]


def _python_values() -> dict:
    return {name: getattr(pid, name) for name in CONSTANT_NAMES}


def _shell_values() -> dict:
    script = REPO_ROOT / "scripts" / "product-identity.sh"
    var_list = " ".join(CONSTANT_NAMES)
    command = (
        f'source "{script}"; '
        f'for v in {var_list}; do printf "%s\\t%s\\n" "$v" "${{!v}}"; done'
    )
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    values = {}
    for line in result.stdout.splitlines():
        name, _, value = line.partition("\t")
        values[name] = value
    return values


def _node_values(node_bin: str) -> dict:
    cjs_path = (REPO_ROOT / "macOS" / "product-identity.js").as_posix()
    esm_path = (REPO_ROOT / "client" / "js" / "product-identity.js").as_posix()
    ts_path = (REPO_ROOT / "web" / "src" / "lib" / "product-identity.ts").as_posix()

    script = f"""
import {{ createRequire }} from 'node:module';
const require = createRequire(import.meta.url);

const cjs = require('{cjs_path}');
const esm = await import('{esm_path}');
const ts = await import('{ts_path}');

const pick = (mod) => {{
    const out = {{}};
    for (const key of {json.dumps(CONSTANT_NAMES)}) {{
        out[key] = mod[key];
    }}
    return out;
}};

console.log(JSON.stringify({{
    cjs: pick(cjs),
    esm: pick(esm),
    ts: pick(ts),
}}));
"""
    result = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def node_bin() -> str:
    resolved = shutil.which("node")
    if not resolved:
        pytest.skip("node is not on PATH; cannot verify the JS/TS mirrors")
    return resolved


class TestProductIdentityParity:
    def test_shell_mirror_matches_python(self) -> None:
        python_values = _python_values()
        shell_values = _shell_values()
        assert shell_values == python_values, (
            "scripts/product-identity.sh has drifted from "
            "src/core/product_identity.py"
        )

    def test_commonjs_mirror_matches_python(self, node_bin: str) -> None:
        python_values = _python_values()
        node_values = _node_values(node_bin)
        assert node_values["cjs"] == python_values, (
            "macOS/product-identity.js has drifted from "
            "src/core/product_identity.py"
        )

    def test_esm_mirror_matches_python(self, node_bin: str) -> None:
        python_values = _python_values()
        node_values = _node_values(node_bin)
        assert node_values["esm"] == python_values, (
            "client/js/product-identity.js has drifted from "
            "src/core/product_identity.py"
        )

    def test_typescript_mirror_matches_python(self, node_bin: str) -> None:
        python_values = _python_values()
        node_values = _node_values(node_bin)
        assert node_values["ts"] == python_values, (
            "web/src/lib/product-identity.ts has drifted from "
            "src/core/product_identity.py"
        )

    def test_all_five_spellings_agree_on_every_constant(self, node_bin: str) -> None:
        python_values = _python_values()
        shell_values = _shell_values()
        node_values = _node_values(node_bin)
        all_sets = {
            "python": python_values,
            "shell": shell_values,
            "commonjs": node_values["cjs"],
            "esm": node_values["esm"],
            "typescript": node_values["ts"],
        }
        for name in CONSTANT_NAMES:
            seen = {label: values[name] for label, values in all_sets.items()}
            distinct = set(seen.values())
            assert len(distinct) == 1, (
                f"{name} disagrees across spellings: {seen}"
            )

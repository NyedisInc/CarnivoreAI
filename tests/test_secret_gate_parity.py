
from __future__ import annotations

import random
import re
import shutil
import string
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / ".gitleaks.toml"
HOOK = REPO_ROOT / "scripts" / "hooks" / "pre-commit-secret-scan.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "secret-scan.yml"

_PIN_RE = re.compile(r"^\s*GITLEAKS_VERSION:\s*([0-9][0-9.]*)", re.M)

_HAS_GITLEAKS = shutil.which("gitleaks") is not None
_needs_gitleaks = pytest.mark.skipif(
    not _HAS_GITLEAKS, reason="gitleaks is not installed on this machine"
)


def _allowlist_regexes() -> list[str]:
    text = CONFIG.read_text()
    marker = "Synthetic credential fixtures in the secret-scanner test suite"
    assert marker in text, "fixture allowlist block is missing"
    tail = text[text.index(marker):]
    next_block = re.search(r"\n\[\[allowlists\]\]", tail)
    block_text = tail[:next_block.start()] if next_block else tail
    blocks = re.findall(r"regexes = \[(.*?)\n\]", block_text, re.S)
    assert blocks, "no regexes block found in the fixture allowlist"
    return re.findall(r"'''(.*?)'''", blocks[-1], re.S)


def test_config_uses_only_the_array_allowlist_form() -> None:
    text = CONFIG.read_text()
    legacy = re.search(r"^\[allowlist\]\s*$", text, re.M)
    array = re.search(r"^\[\[allowlists\]\]\s*$", text, re.M)
    assert array, "expected at least one [[allowlists]] block"
    assert legacy is None, (
        "`[allowlist]` (the legacy table) cannot coexist with `[[allowlists]]`. "
        "gitleaks 8.30.1 fails to load the config entirely, and that exits 1, "
        "which is indistinguishable from 'leaks found' unless you read stderr."
    )


def test_fixture_allowlist_is_scoped_by_value_not_by_path() -> None:
    text = CONFIG.read_text()
    marker = "Synthetic credential fixtures in the secret-scanner test suite"
    assert marker in text, "fixture allowlist block is missing"
    block = text[text.index(marker):]
    assert re.search(r"^\s*paths\s*=", block, re.M) is None, (
        "a `paths =` key was found from the synthetic-fixture allowlist "
        "onward. Value-scoped allowlists in this region must match by "
        "VALUE only - a `paths` entry suppresses the entire file, "
        "including a real credential."
    )


def test_no_dead_allowlist_entries() -> None:
    files = [p for pattern in ("*.py", "*.node.mjs")
             for p in (REPO_ROOT / "tests").rglob(pattern)]
    files += sorted((REPO_ROOT / "tests" / "fixtures").glob("*.json"))
    hay = "\n".join(p.read_text(errors="replace") for p in files)
    for literal in _allowlist_regexes():
        assert literal in hay, (
            f"allowlisted fixture literal (len {len(literal)}) is no longer "
            "used by any test. Remove it from .gitleaks.toml rather than "
            "leaving a standing exemption behind."
        )


def test_jsonl_manifest_allowlist_pattern_matches_live_data() -> None:
    text = CONFIG.read_text()
    marker = "Derived key-order digests in the JSONL shape manifest fixture"
    assert marker in text, "jsonl manifest allowlist block is missing"
    block = text[text.index(marker):]
    match = re.search(r"regexes = \[\s*'''(.*?)'''", block, re.S)
    assert match, "no regex literal found in the jsonl manifest allowlist block"
    pattern = match.group(1)

    manifest = REPO_ROOT / "tests" / "fixtures" / "jsonl_shape_manifest.json"
    assert manifest.exists(), f"{manifest} is missing"
    hits = re.findall(pattern, manifest.read_text())
    assert hits, (
        "the jsonl manifest allowlist regex matches nothing in "
        f"{manifest}. Either the field it targets was renamed or removed "
        "(remove the dead allowlist entry) or the pattern drifted from the "
        "field's real shape (fix the pattern to match it again)."
    )


def test_hook_runs_both_scanners_with_the_repo_config() -> None:
    text = HOOK.read_text()
    assert "scan_secrets.py" in text or "$SCANNER" in text
    assert "gitleaks git --staged" in text, (
        "the hook must run gitleaks too, or it will keep passing commits "
        "that CI rejects"
    )
    assert ".gitleaks.toml" in text, "the hook must use the same config as CI"


def test_hook_can_read_the_pinned_version_from_the_workflow() -> None:
    match = _PIN_RE.search(WORKFLOW.read_text())
    assert match, (
        "could not parse GITLEAKS_VERSION out of the workflow. The hook uses "
        "the same expression, so it has silently lost its parity check."
    )
    assert match.group(1).count(".") >= 1


@_needs_gitleaks
def test_config_loads_in_the_real_gitleaks() -> None:
    done = subprocess.run(
        ["gitleaks", "dir", "--config", str(CONFIG), "--no-banner", "."],
        cwd=REPO_ROOT / "docs",
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert "failed to load config" not in done.stderr.lower(), done.stderr


@_needs_gitleaks
def test_gitleaks_still_reports_a_fresh_secret_in_an_allowlisted_file(
    tmp_path: Path,
) -> None:
    seed = 1337
    alphabet = string.ascii_letters + string.digits
    rng = random.Random(seed)
    planted = "".join(rng.choice(alphabet) for _ in range(40))

    target = tmp_path / "tests"
    target.mkdir()
    src = REPO_ROOT / "tests" / "test_secret_detectors.py"
    (target / src.name).write_text(
        src.read_text() + f'\nAPI_SECRET_KEY = "{planted}"\n'
    )

    done = subprocess.run(
        [
            "gitleaks", "dir", ".",
            "--config", str(CONFIG),
            "--redact", "--no-banner",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode == 1, (
        "gitleaks did NOT report a freshly planted credential inside an "
        "allowlisted fixture file. The allowlist has been widened to cover "
        f"the file rather than the value.\nstdout: {done.stdout}\n"
        f"stderr: {done.stderr}"
    )

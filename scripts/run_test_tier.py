#!/usr/bin/env python3
"""Run the test tier a change needs: smoke always, then client or full.

    every changed path under client/, web/ or docs/   -> CLIENT tier
    anything else, or no changed path at all           -> FULL suite

The client tier is smoke, the python tests that name a touched file or scan
the client/web/docs folders (minus the full_tier browser pixel tests), then
vitest, then every tests/*.node.mjs script six at a time. The full tier is
smoke, then scripts/run-tests.sh unchanged. A server or data change always
runs everything, so the must-run security, data, tmux-identity and status
coverage holds by construction, and the rule is two path prefixes that
cannot go stale without anyone noticing.

`python3 scripts/features.py check` (no --branch) rides alongside smoke on
every run regardless of tier (issue #816): it is stdlib and cheap, and it
catches a malformed features/ JSON file even on a diff that never touched
features/.

Changed paths are `git diff --name-only <trunk remote>/master...HEAD` plus
staged, unstaged and untracked files, all read NUL-separated, so a path with
a space (the repo itself lives under one) or a newline is one path.

Usage::

    python3 scripts/run_test_tier.py            # route by the diff and run
    python3 scripts/run_test_tier.py --plan     # print the route, run nothing
    python3 scripts/run_test_tier.py --smoke    # the smoke tier alone
    python3 scripts/run_test_tier.py --gate     # the 1.0 gate: smoke, then tests/python/gate/, the clean room, the default state walk, the field installs (G4)

Environment: CLOUDE_TEST_WORKERS (default 6), CLOUDE_TIER_BASE (default
<trunk remote>/master, where the trunk remote is resolved BY URL -
scripts/lib/trunk_remote.py, issue #717 - never a hardcoded name, since
remote names are per clone; override the remote alone with
CLOUDE_TRUNK_REMOTE, or the whole base with CLOUDE_TIER_BASE).

Exit codes:
    0  every stage that ran passed
    1  a test failed
    2  could not determine: a listed file is missing, a file or a selection
       collected zero tests, the diff could not be read, or a tool is absent

Exit 2 is NOT a pass. A check that looked at nothing has checked nothing
(CLAUDE.md gotcha 11).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTHON = REPO / "venv" / "bin" / "python3"

sys.path.insert(0, str(REPO))
from scripts.lib.trunk_remote import TrunkRemoteError, trunk_remote_name  # noqa: E402
GATE_TESTS = "tests/python/gate"
SMOKE_LIST = REPO / "tests" / "smoke_files.txt"
FULL_TIER_LIST = REPO / "tests" / "full_tier_files.txt"
RUN_TESTS = REPO / "scripts" / "run-tests.sh"

CLIENT_PREFIXES = ("client/", "web/", "docs/")

FOLDER_RX = re.compile(r"""["'](client|web|docs)["'/]""")

CLIENT_ALLOWLIST_RX = re.compile(r"^(?:tests/[^/]+\.node\.mjs|scripts/verify_[^/]+\.py)$")

FEATURES_DATA_RX = re.compile(r"^features/(?:changes|catalog|capture)/[^/]+\.json$")

FEATURES_MEDIA_RX = re.compile(r"^features/media/[^/]+/[^/]+\.(?:png|webp|gif|svg)$")

BOARDS_DATA_RX = re.compile(r"^design/boards/(?:[^/]+/)?[^/]+$")

BOARDS_TEST = "tests/python/cplugs/reviewboard/test_repo_boards_valid.py"

FEATURES_TEST = "tests/test_features_catalog.py"


def _is_client_eligible(path: str) -> bool:
    return (path.startswith(CLIENT_PREFIXES) or bool(CLIENT_ALLOWLIST_RX.match(path))
            or bool(FEATURES_DATA_RX.match(path)) or bool(FEATURES_MEDIA_RX.match(path)) or bool(BOARDS_DATA_RX.match(path)))


PASS, FAIL, REFUSED = 0, 1, 2
NODE_TIMEOUT_S = 300


class Refusal(Exception):
    """The tier cannot be determined or run; always exit 2, never a pass."""


def read_list(path: Path) -> list[str]:
    if not path.is_file():
        raise Refusal(f"{path.relative_to(REPO)} is missing")
    entries = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    if not entries:
        raise Refusal(f"{path.relative_to(REPO)} lists nothing")
    missing = [e for e in entries if not (REPO / e).is_file()]
    if missing:
        raise Refusal(f"{path.relative_to(REPO)} names missing file(s): {missing}")
    return entries


def _git_paths(repo: Path, *args: str) -> list[str]:
    done = subprocess.run(["git", *args, "-z"], cwd=repo, capture_output=True)
    if done.returncode != 0:
        raise Refusal(f"git {' '.join(args)} failed: {done.stderr.decode(errors='replace').strip()}")
    return [p for p in done.stdout.decode("utf-8", errors="surrogateescape").split("\0") if p]


def changed_paths(repo: Path, base: str) -> list[str]:
    paths = set(_git_paths(repo, "diff", "--name-only", f"{base}...HEAD"))
    paths |= set(_git_paths(repo, "diff", "--name-only", "HEAD"))
    paths |= set(_git_paths(repo, "ls-files", "--others", "--exclude-standard"))
    return sorted(paths)


def route(paths: list[str]) -> str:
    if paths and all(_is_client_eligible(p) for p in paths):
        return "client"
    return "full"


def route_reason(paths: list[str], tier: str) -> str:
    if not paths:
        return "no changed path (an empty diff always runs the full suite)"
    if tier == "full":
        blockers = [p for p in paths if not _is_client_eligible(p)]
        return (f"{len(blockers)} changed path(s) outside client/, web/, docs/ "
                f"and the tests/*.node.mjs / scripts/verify_*.py / "
                f"features/changes|catalog|capture|media allowlist, e.g. {blockers[0]}")
    allowlisted = [p for p in paths if not p.startswith(CLIENT_PREFIXES)]
    if allowlisted:
        return (f"every changed path is under client/, web/, docs/ or the "
                f"tests/*.node.mjs / scripts/verify_*.py / "
                f"features/changes|catalog|capture|media allowlist "
                f"({len(allowlisted)} allowlisted path(s), issues #700/#886/#891)")
    return "every changed path is under client/, web/ or docs/"


def client_python_selection(repo: Path, paths: list[str], exclude: set[str]) -> list[str]:
    names = {Path(p).name for p in paths}
    selected = []
    for test in sorted((repo / "tests").rglob("test_*.py")):
        rel = test.relative_to(repo).as_posix()
        if rel in exclude:
            continue
        text = test.read_text(encoding="utf-8", errors="replace")
        if FOLDER_RX.search(text) or any(n in text for n in names):
            selected.append(rel)
    if (any(FEATURES_DATA_RX.match(p) or FEATURES_MEDIA_RX.match(p) for p in paths)
            and FEATURES_TEST not in exclude and FEATURES_TEST not in selected
            and (repo / FEATURES_TEST).is_file()):
        selected.append(FEATURES_TEST)
    if (any(BOARDS_DATA_RX.match(p) for p in paths)
            and BOARDS_TEST not in exclude and BOARDS_TEST not in selected
            and (repo / BOARDS_TEST).is_file()):
        selected.append(BOARDS_TEST)
    return selected


def serial_only_files() -> list[str]:
    text = RUN_TESTS.read_text(encoding="utf-8")
    block = re.search(r"^SERIAL_ONLY=\((.*?)^\)", text, re.S | re.M)
    files = re.findall(r'"(tests/[^"]+\.py)"', block.group(1)) if block else []
    if not files:
        raise Refusal("could not read SERIAL_ONLY out of scripts/run-tests.sh")
    return files


def _tests_per_file(junit: Path, files: list[str]) -> dict[str, int]:
    counts = dict.fromkeys(files, 0)
    modules = {f: f[:-3].replace("/", ".") for f in files}
    for case in ET.parse(junit).iter("testcase"):
        cls = case.get("classname", "")
        for f, mod in modules.items():
            if cls == mod or cls.startswith(mod + "."):
                counts[f] += 1
                break
    return counts


def run_pytest(label: str, files: list[str], workers: int, marker: str | None = None,
               must_collect: list[str] | None = None) -> int:
    if not files:
        raise Refusal(f"{label}: empty selection")
    with tempfile.TemporaryDirectory(prefix="tier_") as tmp:
        junit = Path(tmp) / "junit.xml"
        cmd = [str(PYTHON), "-m", "pytest", "-q", f"--junitxml={junit}"]
        if workers:
            cmd += ["-n", str(workers)]
        if marker:
            cmd += ["-m", marker]
        print(f"== {label}: {len(files)} file(s)" + (f" at {workers} workers" if workers else ", serially"), flush=True)
        rc = subprocess.run(cmd + files, cwd=REPO).returncode
        if rc == 5 or not junit.is_file():
            print(f"{label}: collected zero tests, a refusal rather than a pass", file=sys.stderr)
            return REFUSED
        empty = [f for f, n in _tests_per_file(junit, must_collect if must_collect is not None else files).items() if n == 0]
    if empty:
        print(f"{label}: these files collected zero tests: {empty}", file=sys.stderr)
        return REFUSED
    return PASS if rc == 0 else FAIL if rc == 1 else REFUSED


def run_gate_script(module: str) -> int:
    """Run one ``scripts/gate`` module (clean room, default state) with the repo venv. Inputs: module (dotted). Output: PASS, FAIL or REFUSED.

    Each exits 0 pass, 1 fail, 2 could not determine, the same codes this tool uses, so the code maps straight through.
    """
    print(f"== {module}", flush=True)
    rc = subprocess.run([str(PYTHON), "-m", module], cwd=REPO).returncode
    return rc if rc in (PASS, FAIL) else REFUSED


def run_features_check() -> int:
    print("== feature catalog: python3 scripts/features.py check", flush=True)
    rc = subprocess.run(["python3", str(REPO / "scripts" / "features.py"), "check"], cwd=REPO).returncode
    return {0: PASS, 1: FAIL}.get(rc, REFUSED)


def run_vitest() -> int:
    if not (REPO / "web" / "node_modules").exists():
        raise Refusal("web/node_modules is missing, so vitest cannot run")
    print("== vitest: npm run test in web/", flush=True)
    rc = subprocess.run(["npm", "run", "test"], cwd=REPO / "web").returncode
    return PASS if rc == 0 else FAIL


def run_node_scripts(workers: int) -> int:
    scripts = sorted((REPO / "tests").rglob("*.node.mjs"))
    if not scripts:
        raise Refusal("no tests/**/*.node.mjs scripts found")
    print(f"== node scripts: {len(scripts)} at {workers} at a time", flush=True)

    def one(script: Path) -> tuple[str, int, str]:
        try:
            done = subprocess.run(["node", str(script)], cwd=REPO, capture_output=True,
                                  text=True, timeout=NODE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return script.name, -1, f"timed out after {NODE_TIMEOUT_S} s"
        return script.name, done.returncode, (done.stdout + done.stderr)[-600:]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, scripts))
    failed = [r for r in results if r[1] != 0]
    for name, rc, tail in failed:
        print(f"node script FAILED: {name} (exit {rc})\n{tail}", file=sys.stderr)
    print(f"node scripts: {len(results) - len(failed)} passed, {len(failed)} failed", flush=True)
    return FAIL if failed else PASS


def _combine(codes: list[int]) -> int:
    return FAIL if FAIL in codes else REFUSED if REFUSED in codes else PASS


def main(argv: list[str]) -> int:
    workers = int(os.environ.get("CLOUDE_TEST_WORKERS", "6"))
    if not PYTHON.is_file():
        raise Refusal(f"{PYTHON} is missing; the system python3 has no pytest")
    smoke = read_list(SMOKE_LIST)
    full_tier = read_list(FULL_TIER_LIST)
    if "--smoke" in argv:
        tier, paths = "smoke", []
        print("run_test_tier: --smoke -> smoke tier only", flush=True)
    elif "--gate" in argv:
        tier, paths = "gate", []
        print("run_test_tier: --gate -> smoke, then the 1.0 gate matrix (#1946)", flush=True)
    else:
        # something else
        base = os.environ.get("CLOUDE_TIER_BASE")
        if not base:
            try:
                base = f"{trunk_remote_name(REPO)}/master"
            except TrunkRemoteError as exc:
                raise Refusal(str(exc)) from exc
        paths = changed_paths(REPO, base)
        tier = route(paths)
        print(f"run_test_tier: {len(paths)} changed path(s) against {base} -> {tier} tier "
              f"({route_reason(paths, tier)})", flush=True)
    for p in paths[:40]:
        print(f"  {p}")
    selection: list[str] = []
    if tier == "client":
        selection = client_python_selection(REPO, paths, set(smoke))
        print(f"  client python selection: {len(selection)} file(s)")
    if "--plan" in argv:
        for f in selection:
            print(f"    {f}")
        return PASS

    stages: list[tuple[str, int, float]] = []

    def stage(name: str, fn, *args, **kwargs) -> int:
        start = time.monotonic()
        try:
            rc = fn(*args, **kwargs)
        except Refusal as exc:
            print(f"{name}: COULD NOT DETERMINE: {exc}", file=sys.stderr)
            rc = REFUSED
        stages.append((name, rc, time.monotonic() - start))
        return rc

    def full_suite() -> int:
        print("== full suite: scripts/run-tests.sh", flush=True)
        rc = subprocess.run(["bash", str(RUN_TESTS)], cwd=REPO).returncode
        return {0: PASS, 1: FAIL}.get(rc, REFUSED)

    smoke_rc = stage("smoke", run_pytest, "smoke", smoke, workers)
    stage("feature catalog", run_features_check)
    if smoke_rc == PASS and tier == "full":
        stage("full suite", full_suite)
    elif smoke_rc == PASS and tier == "gate":
        stage("gate matrix", run_pytest, "gate matrix", [GATE_TESTS], workers, must_collect=[])
        stage("clean room", run_gate_script, "scripts.gate.clean_room")
        stage("default state", run_gate_script, "scripts.gate.default_state")
        stage("field installs", run_gate_script, "scripts.gate.field_installs")
    elif smoke_rc == PASS and tier == "client":
        serial = set(serial_only_files())
        parallel = [f for f in selection if f not in serial]
        late = [f for f in selection if f in serial]
        stage("client python", run_pytest, "client python", parallel, workers,
              marker="not full_tier",
              must_collect=[f for f in parallel if f not in full_tier])
        stage("vitest", run_vitest)
        stage("node scripts", run_node_scripts, workers)
        if late:
            stage("client python, serial files", run_pytest,
                  "client python, serial files", late, 0, marker="not full_tier",
                  must_collect=[f for f in late if f not in full_tier])

    verdict = _combine([rc for _, rc, _ in stages])
    print()
    for name, rc, secs in stages:
        print(f"  {name:<30} {['PASS', 'FAIL', 'COULD NOT DETERMINE'][rc]:<20} {secs:6.1f} s")
    word = ["PASS", "FAIL", "COULD NOT DETERMINE"][verdict]
    sys.stdout.flush()
    print(f"run_test_tier: {word} ({tier} tier)", file=sys.stderr if verdict else sys.stdout)
    return verdict


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Refusal as exc:
        print(f"run_test_tier: COULD NOT DETERMINE: {exc}", file=sys.stderr)
        sys.exit(REFUSED)

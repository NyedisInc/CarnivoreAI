#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import tempfile
import io
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.lib import suite_rerun  # noqa: E402

GREEN = "last-green-ledger.tsv"
RED = "last-red-ledger.jsonl"
NARROW_PREFIXES = ("docs/", "features/changes/", "features/catalog/", "features/capture/", "features/media/")
NARROW_EXACT = {"features/index.json", "features/schema.json", "FEATURES.md"}
DOC_CHECKS = ("tests/plugin_api", "tests/test_docs_index.py", "tests/test_features_catalog.py")


class CarryError(Exception):
    pass


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise CarryError(f"git {' '.join(args)} failed: {done.stderr.strip()[:200]}")
    return done.stdout


def is_narrow(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if path.startswith("tests/") and name.startswith("test_") and name.endswith(".py"):
        return True
    return path.startswith(NARROW_PREFIXES) or path in NARROW_EXACT or path.endswith(".md")


def read_green(out: Path) -> list[dict]:
    f = out / GREEN
    if not f.exists():
        return []
    rows = []
    for line in f.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if cols and cols[0]:
            carried = next((c[8:] for c in cols[5:] if c.startswith("carried:")), "")
            rows.append({"sha": cols[0], "carried": carried, "ids": []})
    return rows


def read_red(out: Path) -> list[dict]:
    f = out / RED
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def is_ancestor(repo: Path, a: str, b: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b], capture_output=True).returncode == 0


def distance(repo: Path, a: str, b: str) -> int:
    return int(git(repo, "rev-list", "--count", f"{a}..{b}").strip())


def find_anchor(repo: Path, out: Path, sha: str, reds_only: bool = False) -> dict | None:
    cands = [{"sha": r["sha"], "kind": "red", "ids": list(r.get("ids", []))} for r in read_red(out)]
    if not reds_only:
        cands += [{"sha": r["sha"], "kind": "green", "ids": []} for r in read_green(out) if not r["carried"]]
    best, best_d = None, None
    for c in cands:
        if not is_ancestor(repo, c["sha"], sha):
            continue
        d = distance(repo, c["sha"], sha)
        if best_d is None or d <= best_d:
            best, best_d = c, d
    return best


def changed_between(repo: Path, anchor: str, sha: str) -> tuple[list[str], list[str]]:
    allp = [p for p in git(repo, "diff", "--name-only", anchor, sha).splitlines() if p]
    kept = [p for p in git(repo, "diff", "--name-only", "--diff-filter=ACMR", anchor, sha).splitlines() if p]
    tests = [p for p in kept if p.startswith("tests/") and is_narrow(p) and p.endswith(".py")]
    return allp, tests


def client_selection(repo: Path, sha: str, paths: list[str]) -> list[str]:
    from scripts import run_test_tier
    raw = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", sha, "tests"], capture_output=True)
    if raw.returncode != 0:
        raise CarryError("git archive of tests failed")
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(fileobj=io.BytesIO(raw.stdout)) as tar:
        tar.extractall(tmp, filter="data")
        return run_test_tier.client_python_selection(Path(tmp), paths, set())


def exists_at(repo: Path, sha: str, path: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}:{path}"], capture_output=True).returncode == 0


def build_targets(repo: Path, sha: str, anchor: dict, with_selection: bool) -> tuple[list[str], list[str]]:
    paths, tests = changed_between(repo, anchor["sha"], sha)
    if not paths and anchor["kind"] == "red":
        raise CarryError("empty diff after a red anchor")
    blockers = [p for p in paths if not is_narrow(p)]
    if blockers:
        raise CarryError(f"{len(blockers)} changed path(s) are not narrow, e.g. {blockers[0]}")
    targets = list(anchor["ids"]) + tests
    if with_selection:
        targets += client_selection(repo, sha, paths)
        if any(p.startswith(("docs/", "features/")) for p in paths):
            targets += [t for t in DOC_CHECKS if exists_at(repo, sha, t)]
    return list(dict.fromkeys(targets)), paths


def plan(repo: Path, out: Path, sha: str) -> dict:
    try:
        anchor = find_anchor(repo, out, sha)
        if anchor is None:
            return {"mode": "full", "reason": "no real full run anchors this sha"}
        targets, paths = build_targets(repo, sha, anchor, True)
        if not targets:
            return {"mode": "full", "reason": "the narrow set selects no tests"}
        return {"mode": "carry", "anchor": anchor["sha"], "paths": len(paths), "targets": targets}
    except (CarryError, OSError, ValueError, tarfile.TarError, ImportError) as exc:
        return {"mode": "full", "reason": f"carry could not decide ({exc})"}


def recheck(repo: Path, out: Path, sha: str) -> dict:
    try:
        anchor = find_anchor(repo, out, sha, reds_only=True)
        if anchor is None:
            return {"ok": False, "reason": "no red record is an ancestor of this sha"}
        paths, tests = changed_between(repo, anchor["sha"], sha)
        targets = list(dict.fromkeys(list(anchor["ids"]) + tests))
        return {"ok": bool(targets), "anchor": anchor["sha"], "targets": targets, "reason": "" if targets else "nothing to recheck"}
    except (CarryError, OSError, ValueError) as exc:
        return {"ok": False, "reason": f"recheck could not read its inputs ({exc})"}


def record_red(out: Path, sha: str, host: str, rc: int, log: Path, fails: Path, flakes: Path) -> bool:
    try:
        if not suite_rerun.normal_failure(rc, log.read_text(errors="replace")):
            return False
        ids = suite_rerun.parse_ids(fails.read_text()) if fails.exists() else []
        skip = set(suite_rerun.parse_ids(flakes.read_text())) if flakes.exists() else set()
        skip |= {l.strip() for l in flakes.read_text().splitlines()} if flakes.exists() else set()
        ids = [i for i in ids if i not in skip]
        if not ids:
            return False
        out.mkdir(parents=True, exist_ok=True)
        with (out / RED).open("a", encoding="utf-8") as f:
            f.write(json.dumps({"sha": sha, "host": host, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ids": ids}) + "\n")
        return True
    except OSError:
        return False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["record-red", "plan", "recheck", "carried-row", "verdict"])
    ap.add_argument("--out", default="")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--sha", default="")
    ap.add_argument("--host", default="")
    ap.add_argument("--rc", type=int, default=0)
    ap.add_argument("--log", default="")
    ap.add_argument("--fails", default="")
    ap.add_argument("--flakes", default="")
    ap.add_argument("--secs", default="0")
    ap.add_argument("--anchor", default="")
    ap.add_argument("--ids-file", default="")
    a = ap.parse_args(argv)
    out, repo = Path(a.out), Path(a.repo)
    if a.cmd == "plan":
        print(json.dumps(plan(repo, out, a.sha)))
    elif a.cmd == "recheck":
        r = recheck(repo, out, a.sha)
        print(json.dumps(r))
        return 0 if r["ok"] else 2
    elif a.cmd == "record-red":
        print("recorded" if record_red(out, a.sha, a.host, a.rc, Path(a.log), Path(a.fails), Path(a.flakes)) else "not recorded")
    elif a.cmd == "carried-row":
        with (out / GREEN).open("a", encoding="utf-8") as f:
            f.write("\t".join([a.sha, a.host, a.secs, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "0", f"carried:{a.anchor}"]) + "\n")
    elif a.cmd == "verdict":
        ids = [l for l in Path(a.ids_file).read_text().splitlines() if l]
        still = set(suite_rerun.parse_ids(Path(a.fails).read_text())) if Path(a.fails).exists() else set()
        print("now pass: " + (", ".join(i for i in ids if i not in still) or "none"))
        print("still fail: " + (", ".join(i for i in ids if i in still) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
